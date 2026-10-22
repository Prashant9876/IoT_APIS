import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.core import (
    check_timestamp_format,
    mqtt_client,
    upload_sensor_import_metadata_to_s3,
    upload_sensor_import_to_s3,
    validate_api_key,
)


router = APIRouter()
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

FIXED_FIELDS_BY_DN = {
    "THC": ["Etemp", "Humidity", "CO2", "DN", "Device_Id", "Packet_Id", "timestamp"],
    "NSD": [
        "PH Sensor",
        "EC Sensor",
        "Water Temperature Sensor",
        "rack",
        "shelve",
        "cases",
        "eventId",
        "Packet_Id",
        "Device_Id",
        "DN",
        "timestamp",
    ],
    "WLD": ["WaterLevel", "Device_Id", "Packet_Id", "rack_id", "DN", "timestamp"],
    "PPFD": ["PPFD", "shelve", "rack", "Device_Id", "Packet_Id", "DN", "timestamp"],
}
ALLOWED_DN = set(FIXED_FIELDS_BY_DN)
CUSTOM_TIMESTAMP_FORMATS = {
    "Custom String: %d/%m/%Y %H:%M:%S": "%d/%m/%Y %H:%M:%S",
    "Custom String: %d/%m/%Y %H:%M": "%d/%m/%Y %H",
    "Custom String: %d-%m-%Y %H:%M:%S": "%d-%m-%Y %H:%M:%S",
    "Custom String: %d-%m-%Y %H:%M": "%d-%m-%Y %H",
    "Custom String: %Y-%m-%d %H:%M:%S": "%Y-%m-%d %H:%M:%S",
    "Custom String: %Y-%m-%d %H:%M": "%Y-%m-%d %H:%M",
}
SUPPORTED_TIMESTAMP_FORMATS = (
    "Excel Native Date/Time, Excel Native Serial Number, ISO 8601 String, "
    "Unix Epoch Timestamp in Seconds, Epoch Timestamp in Milliseconds, or "
    "DD/MM/YYYY HH:MM[:SS], DD-MM-YYYY HH:MM[:SS], YYYY-MM-DD HH:MM[:SS]."
)


def _parse_timestamp_to_utc(value, detected_format: str, source_timezone: ZoneInfo) -> str:
    """Convert one supported timestamp value to an ISO-8601 UTC string."""
    if detected_format == "Unix Epoch Timestamp in Seconds":
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif detected_format == "Epoch Timestamp in Milliseconds":
        parsed = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    elif detected_format == "Excel Native Serial Number":
        parsed = pd.Timestamp("1899-12-30") + pd.to_timedelta(float(value), unit="D")
    elif detected_format == "Excel Native Date/Time":
        parsed = pd.Timestamp(value).to_pydatetime()
    elif detected_format == "ISO 8601 String":
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    else:
        parsed = datetime.strptime(str(value).strip(), CUSTOM_TIMESTAMP_FORMATS[detected_format])

    if isinstance(parsed, pd.Timestamp):
        parsed = parsed.to_pydatetime()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=source_timezone)

    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_records(dataframe: pd.DataFrame) -> list[dict]:
    """Return JSON-safe records while retaining numeric spreadsheet values."""
    return json.loads(dataframe.to_json(orient="records", date_format="iso"))


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or pd.isna(value)


def _add_fixed_fields(dataframe: pd.DataFrame, dn: str, device_id) -> pd.DataFrame:
    """Ensure every published record follows the fixed schema for its DN."""
    for field in FIXED_FIELDS_BY_DN[dn]:
        if field not in dataframe.columns:
            dataframe[field] = "N/A"
        else:
            dataframe[field] = dataframe[field].map(lambda value: "N/A" if _is_missing(value) else value)

    # Metadata is authoritative for the identity fields in every MQTT payload.
    dataframe["DN"] = dn
    dataframe["Device_Id"] = device_id
    return dataframe


@router.post("/api/excel-upload")
async def upload_excel(
    file: UploadFile = File(...),
    metadata: str = Form(...),
    x_api_key: Optional[str] = Header(default=None),
):
    validate_api_key(x_api_key)

    try:
        metadata_json = json.loads(metadata)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="metadata must be valid JSON") from error

    dn = str(metadata_json.get("dn", "")).upper()
    device_id = metadata_json.get("device_id")
    farm_id = metadata_json.get("farm_id")
    source_timezone_name = metadata_json.get("source_timezone", "Asia/Kolkata")

    if dn not in ALLOWED_DN:
        raise HTTPException(status_code=400, detail="dn must be THC, NSD, WLD, or PPFD")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id is required")
    if farm_id is None or str(farm_id).strip() == "":
        raise HTTPException(status_code=400, detail="farm_id is required")

    try:
        source_timezone = ZoneInfo(source_timezone_name)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(status_code=400, detail="source_timezone must be a valid IANA timezone") from error

    extension = Path(file.filename or "").suffix.lower()
    if extension not in {".xlsx", ".xls", ".csv"}:
        raise HTTPException(status_code=400, detail="Only .xlsx, .xls and .csv files are allowed")

    import_id = f"imp_{uuid.uuid4().hex[:12]}"
    saved_file_path = UPLOAD_DIR / f"{import_id}{extension}"
    processed_file_path = UPLOAD_DIR / f"{import_id}_utc_sorted{'.csv' if extension == '.csv' else '.xlsx'}"

    with saved_file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        if extension == ".csv":
            dataframe = pd.read_csv(saved_file_path)
            sheets = ["CSV"]
        else:
            excel_file = pd.ExcelFile(saved_file_path)
            sheets = excel_file.sheet_names
            dataframe = pd.read_excel(saved_file_path, sheet_name=sheets[0])

        if "timestamp" not in dataframe.columns:
            raise HTTPException(status_code=400, detail="Excel file must contain a timestamp column")

        missing_timestamp_rows = (dataframe[dataframe["timestamp"].isna()].index + 2).tolist()
        if missing_timestamp_rows:
            raise HTTPException(
                status_code=400,
                detail=f"timestamp is required at Excel row(s) {missing_timestamp_rows}",
            )

        timestamps = dataframe["timestamp"]

        detected_formats = timestamps.map(check_timestamp_format)
        if (detected_formats == "Unknown timestamp format").any():
            invalid_rows = (detected_formats[detected_formats == "Unknown timestamp format"].index + 2).tolist()
            raise HTTPException(
                status_code=400,
                detail=f"Invalid timestamp format at Excel row(s) {invalid_rows}. Supported formats: {SUPPORTED_TIMESTAMP_FORMATS}",
            )

        unique_formats = detected_formats.unique().tolist()
        if len(unique_formats) != 1:
            raise HTTPException(
                status_code=400,
                detail=f"All timestamp values must use one format. Found: {', '.join(unique_formats)}",
            )

        detected_format = unique_formats[0]
        print("Detected format:", detected_format)

        if "DN" in dataframe.columns:
            sheet_dns = {str(value).upper() for value in dataframe["DN"].dropna()}
            if sheet_dns and sheet_dns != {dn}:
                raise HTTPException(status_code=400, detail="DN values in the file must match metadata.dn")

        dataframe["timestamp_utc"] = dataframe["timestamp"].map(
            lambda value: _parse_timestamp_to_utc(value, detected_format, source_timezone)
            if pd.notna(value)
            else None
        )
        dataframe = _add_fixed_fields(dataframe, dn, device_id)
        dataframe = dataframe.sort_values("timestamp_utc", ascending=True, na_position="last").reset_index(drop=True)

        if extension == ".csv":
            dataframe.to_csv(processed_file_path, index=False)
        else:
            dataframe.to_excel(processed_file_path, index=False)
    except HTTPException:
        saved_file_path.unlink(missing_ok=True)
        processed_file_path.unlink(missing_ok=True)
        raise
    except Exception as error:
        saved_file_path.unlink(missing_ok=True)
        processed_file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Unable to read Excel file: {error}") from error

    topic = f"farm/{farm_id}/sensor"
    records = _json_records(dataframe)
    import_metadata = {
        "import_id": import_id,
        "status": "stored_pending_publish",
        "farm_id": farm_id,
        "dn": dn,
        "device_id": device_id,
        "source_timezone": source_timezone_name,
        "timestamp_format": detected_format,
        "mqtt_topic": topic,
        "original_file_name": file.filename,
        "processed_file_name": processed_file_path.name,
        "total_rows": len(dataframe),
        "published_records": 0,
        "uploaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "request_metadata": metadata_json,
    }
    s3_result = upload_sensor_import_to_s3(
        farm_id=farm_id,
        dn=dn,
        device_id=device_id,
        import_id=import_id,
        original_file_path=saved_file_path,
        processed_file_path=processed_file_path,
        metadata=import_metadata,
    )
    if not s3_result["success"]:
        raise HTTPException(status_code=502, detail=s3_result["message"])

    def update_s3_metadata(status: str, published_records: int, error: Optional[str] = None) -> dict:
        import_metadata["status"] = status
        import_metadata["published_records"] = published_records
        import_metadata["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        if error:
            import_metadata["error"] = error
        return upload_sensor_import_metadata_to_s3(s3_result["metadata_key"], import_metadata)

    if not mqtt_client.connected:
        metadata_result = update_s3_metadata("mqtt_disconnected", 0)
        if metadata_result["success"]:
            saved_file_path.unlink(missing_ok=True)
            processed_file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail="MQTT broker is disconnected; import was saved to S3 but no sensor records were published")

    published_records = 0
    try:
        for record in records:
            record["DN"] = dn
            record["FarmID"] = farm_id
            record["DeviceID"] = device_id
            if not mqtt_client.publish(topic, record):
                raise RuntimeError("MQTT publish failed")
            published_records += 1
    except Exception as error:
        update_s3_metadata("partial_publish", published_records, str(error))
        raise HTTPException(
            status_code=502,
            detail=f"MQTT publishing stopped after {published_records} record(s); import remains in S3",
        ) from error

    metadata_result = update_s3_metadata("published", published_records)
    if not metadata_result["success"]:
        raise HTTPException(status_code=502, detail="Records were published but S3 metadata could not be finalized")

    saved_file_path.unlink(missing_ok=True)
    processed_file_path.unlink(missing_ok=True)

    return {
        "import_id": import_id,
        "status": "published",
        "file_name": file.filename,
        "s3_bucket": s3_result["bucket"],
        "s3_prefix": s3_result["prefix"],
        "original_s3_key": s3_result["original_key"],
        "processed_s3_key": s3_result["processed_key"],
        "metadata_s3_key": s3_result["metadata_key"],
        "farm_id": farm_id,
        "dn": dn,
        "device_id": device_id,
        "source_timezone": source_timezone_name,
        "timestamp_format": detected_format,
        "topic": topic,
        "published_records": len(records),
        "available_sheets": sheets,
        "selected_sheet": sheets[0],
        "total_rows": len(dataframe),
        "detected_columns": dataframe.columns.tolist(),
        "sample_rows": records[:5],
    }
