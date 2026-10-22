import io
import json

import pandas as pd
import pytest

from fastapi.testclient import TestClient

from app import core
from app.main import app
from app.routers import excel_uploader


client = TestClient(app)
API_KEY = "test-api-key"


def _mock_s3_upload(*_args, **_kwargs):
    return {
        "success": True,
        "bucket": "test-sensor-imports",
        "prefix": "sensor-imports/farm_id=224/dn=THC/device_id=test/import_id=test",
        "original_key": "original/sensor.csv",
        "processed_key": "processed/sensor_utc_sorted.csv",
        "metadata_key": "metadata.json",
    }


def _upload_csv(monkeypatch, tmp_path, csv_data: str, metadata: dict):
    published = []

    def fake_publish(topic, payload, qos=1, retain=False):
        published.append((topic, payload))
        return True

    monkeypatch.setattr(excel_uploader, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(core.mqtt_client, "connected", True)
    monkeypatch.setattr(core.mqtt_client, "publish", fake_publish)
    monkeypatch.setattr(excel_uploader, "upload_sensor_import_to_s3", _mock_s3_upload)
    monkeypatch.setattr(excel_uploader, "upload_sensor_import_metadata_to_s3", lambda *_args, **_kwargs: {"success": True})

    response = client.post(
        "/api/excel-upload",
        headers={"x-api-key": API_KEY},
        data={"metadata": json.dumps(metadata)},
        files={"file": ("sensor.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )
    return response, published


def test_excel_upload_converts_sorts_and_publishes_sequentially(monkeypatch, tmp_path):
    response, published = _upload_csv(
        monkeypatch,
        tmp_path,
        "timestamp,Etemp,DN\n2026-10-21 10:00:00,25.5,THC\n2026-10-21 09:00:00,24.1,THC\n",
        {
            "dn": "THC",
            "device_id": "IFTHC2240000001",
            "farm_id": 224,
            "source_timezone": "Asia/Kolkata",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["topic"] == "farm/224/sensor"
    assert body["published_records"] == 2
    assert body["sample_rows"][0]["timestamp"] == "2026-10-21T03:30:00Z"
    assert body["sample_rows"][0]["local_time"] == "2026-10-21 09:00:00"
    assert body["sample_rows"][0]["timezone"] == "Asia/Kolkata"
    assert len(published) == 2
    assert [item[0] for item in published] == ["farm/224/sensor", "farm/224/sensor"]
    assert [item[1]["timestamp"] for item in published] == [
        "2026-10-21T03:30:00Z",
        "2026-10-21T04:30:00Z",
    ]
    assert published[0][1]["FarmID"] == 224
    assert published[0][1]["DN"] == "THC"
    assert published[0][1]["DeviceID"] == "IFTHC2240000001"
    assert published[0][1]["CO2"] == "N/A"
    assert published[0][1]["Packet_Id"] == "N/A"
    assert published[0][1]["Device_Id"] == "IFTHC2240000001"
    assert not (tmp_path / f"{body['import_id']}_utc_sorted.csv").exists()
    assert body["s3_bucket"] == "test-sensor-imports"
    assert body["metadata_s3_key"] == "metadata.json"


def test_excel_upload_rejects_unsupported_timestamp_format(monkeypatch, tmp_path):
    response, published = _upload_csv(
        monkeypatch,
        tmp_path,
        "timestamp,Etemp\n10/21/2026 10:00:00,25.5\n",
        {"dn": "THC", "device_id": "IFTHC2240000001", "farm_id": 224},
    )

    assert response.status_code == 400
    assert "Invalid timestamp format" in response.json()["detail"]
    assert published == []


def test_excel_file_adds_utc_column_and_publishes(monkeypatch, tmp_path):
    published = []

    def fake_publish(topic, payload, qos=1, retain=False):
        published.append((topic, payload))
        return True

    workbook = io.BytesIO()
    pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-10-21 10:00:00")],
            "Humidity": [60],
            "DN": ["THC"],
        }
    ).to_excel(workbook, index=False)
    workbook.seek(0)

    monkeypatch.setattr(excel_uploader, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(core.mqtt_client, "connected", True)
    monkeypatch.setattr(core.mqtt_client, "publish", fake_publish)
    monkeypatch.setattr(excel_uploader, "upload_sensor_import_to_s3", _mock_s3_upload)
    monkeypatch.setattr(excel_uploader, "upload_sensor_import_metadata_to_s3", lambda *_args, **_kwargs: {"success": True})

    response = client.post(
        "/api/excel-upload",
        headers={"x-api-key": API_KEY},
        data={
            "metadata": json.dumps(
                {
                    "dn": "THC",
                    "device_id": "IFTHC2240000001",
                    "farm_id": 224,
                    "source_timezone": "Asia/Kolkata",
                }
            )
        },
        files={"file": ("sensor.xlsx", workbook, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert response.json()["sample_rows"][0]["timestamp"] == "2026-10-21T04:30:00Z"
    assert published[0][0] == "farm/224/sensor"
    assert published[0][1]["Humidity"] == 60


@pytest.mark.parametrize(
    ("timestamp", "expected_format"),
    [
        ("21/10/2026 10:00:00", "Custom String: %d/%m/%Y %H:%M:%S"),
        ("21/10/2026 10:00", "Custom String: %d/%m/%Y %H:%M"),
        ("21-10-2026 10:00", "Custom String: %d-%m-%Y %H:%M"),
        ("2026-10-21T10:00:00", "ISO 8601 String"),
        ("2026-10-21T10:00:00Z", "ISO 8601 String"),
        ("2026-10-21T10:00:00+05:30", "ISO 8601 String"),
        ("1761049800", "Unix Epoch Timestamp in Seconds"),
        ("1761049800000", "Epoch Timestamp in Milliseconds"),
    ],
)
def test_excel_upload_accepts_supported_timestamp_styles(monkeypatch, tmp_path, timestamp, expected_format):
    response, published = _upload_csv(
        monkeypatch,
        tmp_path,
        f"timestamp,Etemp\n{timestamp},25.5\n",
        {
            "dn": "THC",
            "device_id": "IFTHC2240000001",
            "farm_id": 224,
            "source_timezone": "Asia/Kolkata",
        },
    )

    assert response.status_code == 200
    assert response.json()["timestamp_format"] == expected_format
    assert published[0][0] == "farm/224/sensor"


def test_excel_serial_timestamp_is_rounded_to_the_nearest_second(monkeypatch, tmp_path):
    response, published = _upload_csv(
        monkeypatch,
        tmp_path,
        "timestamp,Etemp\n46317.3333333333,25.5\n",
        {
            "dn": "THC",
            "device_id": "IFTHC2240000001",
            "farm_id": 224,
            "source_timezone": "Asia/Kolkata",
        },
    )

    assert response.status_code == 200
    assert response.json()["timestamp_format"] == "Excel Native Serial Number"
    assert published[0][1]["timestamp"] == "2026-10-22T02:30:00Z"


def test_nsd_cases_last_is_preserved_and_missing_fixed_fields_are_na(monkeypatch, tmp_path):
    response, published = _upload_csv(
        monkeypatch,
        tmp_path,
        "timestamp,cases,EC Sensor\n2026-10-21 10:00:00,last,1.8\n",
        {
            "dn": "NSD",
            "device_id": "IFNSD2240000001",
            "farm_id": 224,
            "source_timezone": "Asia/Kolkata",
        },
    )

    assert response.status_code == 200
    assert published[0][0] == "farm/224/sensor"
    assert published[0][1]["cases"] == "last"
    assert published[0][1]["PH Sensor"] == "N/A"
    assert published[0][1]["Water Temperature Sensor"] == "N/A"


def test_smd_upload_publishes_expected_soil_sensor_payload(monkeypatch, tmp_path):
    response, published = _upload_csv(
        monkeypatch,
        tmp_path,
        "timestamp,Soil_Moist_10,Soil_Moist_30,Soil_Temp,rack,shelve\n"
        "2026-10-22 08:30:00,10,40,23.45,1,2\n",
        {
            "dn": "SMD",
            "device_id": "IFSMD2240000001",
            "farm_id": 224,
            "source_timezone": "Asia/Kolkata",
        },
    )

    assert response.status_code == 200
    assert published[0][0] == "farm/224/sensor"
    assert published[0][1] == {
        "timestamp": "2026-10-22T03:00:00Z",
        "Soil_Moist_10": 10,
        "Soil_Moist_30": 40,
        "Soil_Temp": 23.45,
        "rack": 1,
        "shelve": 2,
        "local_time": "2026-10-22 08:30:00",
        "timezone": "Asia/Kolkata",
        "Device_Id": "IFSMD2240000001",
        "DN": "SMD",
        "FarmID": 224,
        "DeviceID": "IFSMD2240000001",
    }


def test_excel_upload_does_not_publish_when_s3_upload_fails(monkeypatch, tmp_path):
    published = []

    def fake_publish(topic, payload, qos=1, retain=False):
        published.append((topic, payload))
        return True

    monkeypatch.setattr(excel_uploader, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(core.mqtt_client, "connected", True)
    monkeypatch.setattr(core.mqtt_client, "publish", fake_publish)
    monkeypatch.setattr(
        excel_uploader,
        "upload_sensor_import_to_s3",
        lambda *_args, **_kwargs: {"success": False, "message": "Sensor import S3 upload failed"},
    )

    response = client.post(
        "/api/excel-upload",
        headers={"x-api-key": API_KEY},
        data={
            "metadata": json.dumps(
                {"dn": "THC", "device_id": "IFTHC2240000001", "farm_id": 224}
            )
        },
        files={
            "file": (
                "sensor.csv",
                io.BytesIO(b"timestamp,Etemp\n2026-10-21 10:00:00,25.5\n"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 502
    assert published == []
    assert len(list(tmp_path.iterdir())) == 2


def test_sensor_import_s3_helper_uploads_files_and_metadata(monkeypatch, tmp_path):
    uploaded = {}

    class FakeS3Client:
        def put_object(self, **kwargs):
            body = kwargs["Body"]
            uploaded[kwargs["Key"]] = body.read() if hasattr(body, "read") else body

    original_file = tmp_path / "sensor.csv"
    processed_file = tmp_path / "sensor_utc_sorted.csv"
    original_file.write_text("timestamp,Etemp\n2026-10-21 10:00:00,25.5\n")
    processed_file.write_text("local_time,timestamp,timezone,Etemp\n2026-10-21 10:00:00,2026-10-21T04:30:00Z,Asia/Kolkata,25.5\n")
    monkeypatch.setattr(core, "SENSOR_IMPORT_S3_BUCKET", "test-sensor-imports")
    monkeypatch.setattr(core, "sensor_import_s3_client", FakeS3Client())

    result = core.upload_sensor_import_to_s3(
        farm_id=224,
        dn="THC",
        device_id="IFTHC2240000001",
        import_id="imp_test123",
        original_file_path=original_file,
        processed_file_path=processed_file,
        metadata={"import_id": "imp_test123", "status": "stored_pending_publish"},
    )

    assert result["success"] is True
    assert result["original_key"].endswith("/original/sensor.csv")
    assert result["processed_key"].endswith("/processed/sensor_utc_sorted.csv")
    assert result["metadata_key"].endswith("/metadata.json")
    assert uploaded[result["original_key"]].startswith(b"timestamp,Etemp")
    assert json.loads(uploaded[result["metadata_key"]])["status"] == "stored_pending_publish"
