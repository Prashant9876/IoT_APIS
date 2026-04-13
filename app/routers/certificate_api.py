import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import tempfile
from typing import List

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core import validate_api_key

router = APIRouter()

DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class GenerateCertificateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    farm_id: str = Field(..., alias="farmID")
    device_ids_list: List[str] = Field(..., alias="DeviceIDS_list")
    dry_run: bool = Field(False, alias="dry_run")


def _run_cmd(cmd: List[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise HTTPException(
            status_code=500,
            detail=f"OpenSSL command failed: {stderr or 'unknown error'}",
        ) from exc


def _validate_device_ids(device_ids: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    duplicates = set()
    invalid = []

    for raw in device_ids:
        device_id = raw.strip()
        if not device_id or not DEVICE_ID_PATTERN.fullmatch(device_id):
            invalid.append(raw)
            continue
        if device_id in seen:
            duplicates.add(device_id)
            continue
        cleaned.append(device_id)
        seen.add(device_id)

    if invalid or duplicates:
        parts = []
        if invalid:
            parts.append(f"invalid ids: {sorted(invalid)}")
        if duplicates:
            parts.append(f"duplicate ids: {sorted(duplicates)}")
        raise HTTPException(status_code=400, detail="; ".join(parts))

    return cleaned


def _upload_text_object(
    s3_client,
    bucket: str,
    key: str,
    body: bytes,
    kms_key_id: str,
    content_type: str,
) -> None:
    extra_args = {"ServerSideEncryption": "AES256"}
    if kms_key_id:
        extra_args = {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": kms_key_id,
        }

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
        **extra_args,
    )


@router.post("/generate_certificate")
async def generate_certificate(
    request: GenerateCertificateRequest, x_api_key: str = Header(None)
):
    validate_api_key(x_api_key)

    farm_id = request.farm_id.strip()
    if not farm_id:
        raise HTTPException(status_code=400, detail="farmID is required")

    if "/" in farm_id:
        raise HTTPException(status_code=400, detail="farmID must not contain '/'")

    if not request.device_ids_list:
        raise HTTPException(status_code=400, detail="DeviceIDS_list must not be empty")

    device_ids = _validate_device_ids(request.device_ids_list)

    ca_crt_path = os.getenv("CERT_CA_CRT_PATH", "/etc/mosquitto/certs/ca.crt")
    ca_key_path = os.getenv("CERT_CA_KEY_PATH", "/etc/mosquitto/certs/ca.key")
    bucket = os.getenv("CERT_S3_BUCKET", "IoT_certificate")
    region = os.getenv("AWS_REGION", "ap-south-1")
    kms_key_id = os.getenv("CERT_S3_KMS_KEY_ID", "")
    validity_days = int(os.getenv("CERT_VALIDITY_DAYS", "3650"))

    country = os.getenv("CERT_SUBJ_COUNTRY", "IN")
    state = os.getenv("CERT_SUBJ_STATE", "Karnataka")
    locality = os.getenv("CERT_SUBJ_LOCALITY", "Bengaluru")
    org = os.getenv("CERT_SUBJ_ORG", "Innofarm")

    if not pathlib.Path(ca_crt_path).is_file() or not pathlib.Path(ca_key_path).is_file():
        raise HTTPException(
            status_code=500,
            detail="CA files are missing. Configure CERT_CA_CRT_PATH and CERT_CA_KEY_PATH.",
        )

    try:
        s3_client = boto3.client("s3", region_name=region)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to initialize S3 client: {exc}") from exc

    created = []
    failed = []
    now_utc = dt.datetime.now(dt.timezone.utc).isoformat()

    try:
        with tempfile.TemporaryDirectory(prefix="mqtt-certs-") as tmp:
            work_dir = pathlib.Path(tmp)
            serial_file = work_dir / "ca.srl"

            for device_id in device_ids:
                s3_prefix = f"{farm_id}/{device_id}"
                try:
                    if not request.dry_run:
                        key_path = work_dir / f"{device_id}.key"
                        csr_path = work_dir / f"{device_id}.csr"
                        crt_path = work_dir / f"{device_id}.crt"

                        subject = (
                            f"/C={country}/ST={state}/L={locality}"
                            f"/O={org}/OU=Devices/CN={device_id}"
                        )

                        _run_cmd(["openssl", "genrsa", "-out", str(key_path), "2048"])
                        _run_cmd(
                            [
                                "openssl",
                                "req",
                                "-new",
                                "-key",
                                str(key_path),
                                "-subj",
                                subject,
                                "-out",
                                str(csr_path),
                            ]
                        )

                        sign_cmd = [
                            "openssl",
                            "x509",
                            "-req",
                            "-in",
                            str(csr_path),
                            "-CA",
                            ca_crt_path,
                            "-CAkey",
                            ca_key_path,
                            "-CAserial",
                            str(serial_file),
                            "-out",
                            str(crt_path),
                            "-days",
                            str(validity_days),
                            "-sha256",
                        ]
                        if not serial_file.exists():
                            sign_cmd.append("-CAcreateserial")
                        _run_cmd(sign_cmd)
                        csr_path.unlink(missing_ok=True)

                        with open(ca_crt_path, "rb") as f:
                            _upload_text_object(
                                s3_client=s3_client,
                                bucket=bucket,
                                key=f"{s3_prefix}/ca.crt",
                                body=f.read(),
                                kms_key_id=kms_key_id,
                                content_type="application/x-pem-file",
                            )

                        with open(crt_path, "rb") as f:
                            _upload_text_object(
                                s3_client=s3_client,
                                bucket=bucket,
                                key=f"{s3_prefix}/client.crt",
                                body=f.read(),
                                kms_key_id=kms_key_id,
                                content_type="application/x-pem-file",
                            )

                        with open(key_path, "rb") as f:
                            _upload_text_object(
                                s3_client=s3_client,
                                bucket=bucket,
                                key=f"{s3_prefix}/client.key",
                                body=f.read(),
                                kms_key_id=kms_key_id,
                                content_type="application/x-pem-file",
                            )

                        metadata = {
                            "farmID": farm_id,
                            "device_id": device_id,
                            "issued_at_utc": now_utc,
                            "validity_days": validity_days,
                            "bucket": bucket,
                            "prefix": farm_id,
                        }
                        _upload_text_object(
                            s3_client=s3_client,
                            bucket=bucket,
                            key=f"{s3_prefix}/metadata.json",
                            body=json.dumps(metadata, indent=2).encode("utf-8"),
                            kms_key_id=kms_key_id,
                            content_type="application/json",
                        )

                    created.append(
                        {
                            "device_id": device_id,
                            "s3_path": f"s3://{bucket}/{s3_prefix}/",
                            "mode": "dry_run" if request.dry_run else "generated",
                        }
                    )
                except Exception as exc:
                    failed.append(
                        {
                            "device_id": device_id,
                            "s3_path": f"s3://{bucket}/{s3_prefix}/",
                            "error": str(exc),
                        }
                    )
    except HTTPException:
        raise
    except (ClientError, BotoCoreError) as exc:
        raise HTTPException(status_code=500, detail=f"S3 upload failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Certificate generation failed: {exc}") from exc

    status = "success" if not failed else "partial_success"
    if failed and not created:
        status = "failed"

    return {
        "status": status,
        "bucket": bucket,
        "prefix": farm_id,
        "dry_run": request.dry_run,
        "generated_count": len(created),
        "failed_count": len(failed),
        "devices": created,
        "failed_devices": failed,
    }
