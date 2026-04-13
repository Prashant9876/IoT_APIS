#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import tempfile
from typing import List

import boto3


def run_cmd(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True)


def generate_device_cert(
    device_id: str,
    out_dir: pathlib.Path,
    ca_crt_path: str,
    ca_key_path: str,
    days: int,
    country: str,
    state: str,
    locality: str,
    org: str,
) -> None:
    key_path = out_dir / f"{device_id}.key"
    csr_path = out_dir / f"{device_id}.csr"
    crt_path = out_dir / f"{device_id}.crt"

    subj = (
        f"/C={country}/ST={state}/L={locality}/O={org}/OU=Devices/CN={device_id}"
    )

    run_cmd(["openssl", "genrsa", "-out", str(key_path), "2048"])
    run_cmd(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(key_path),
            "-subj",
            subj,
            "-out",
            str(csr_path),
        ]
    )
    run_cmd(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr_path),
            "-CA",
            ca_crt_path,
            "-CAkey",
            ca_key_path,
            "-CAcreateserial",
            "-out",
            str(crt_path),
            "-days",
            str(days),
            "-sha256",
        ]
    )
    csr_path.unlink(missing_ok=True)


def upload_device_bundle(
    s3_client,
    bucket: str,
    prefix: str,
    kms_key_id: str,
    device_id: str,
    ca_crt_path: str,
    device_crt_path: pathlib.Path,
    device_key_path: pathlib.Path,
    days: int,
) -> None:
    now_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    metadata = {
        "device_id": device_id,
        "issued_at_utc": now_utc,
        "validity_days": days,
    }

    base = prefix.rstrip("/")
    device_base = f"{base}/{device_id}"

    extra_args = {"ServerSideEncryption": "AES256"}
    if kms_key_id:
        extra_args = {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": kms_key_id,
        }

    with open(ca_crt_path, "rb") as f:
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{device_base}/ca.crt",
            Body=f.read(),
            ContentType="application/x-pem-file",
            **extra_args,
        )

    with open(device_crt_path, "rb") as f:
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{device_base}/client.crt",
            Body=f.read(),
            ContentType="application/x-pem-file",
            **extra_args,
        )

    with open(device_key_path, "rb") as f:
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{device_base}/client.key",
            Body=f.read(),
            ContentType="application/x-pem-file",
            **extra_args,
        )

    s3_client.put_object(
        Bucket=bucket,
        Key=f"{device_base}/metadata.json",
        Body=json.dumps(metadata, indent=2).encode("utf-8"),
        ContentType="application/json",
        **extra_args,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate MQTT client certs per device and upload to S3."
    )
    parser.add_argument(
        "--device-ids",
        nargs="+",
        required=True,
        help="Space-separated device IDs. Example: esp32-001 esp32-002",
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument(
        "--prefix",
        default="mqtt-device-certs",
        help="S3 key prefix (default: mqtt-device-certs)",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", "ap-south-1"),
        help="AWS region (default: AWS_REGION env or ap-south-1)",
    )
    parser.add_argument(
        "--ca-crt",
        default="/etc/mosquitto/certs/ca.crt",
        help="Path to CA certificate",
    )
    parser.add_argument(
        "--ca-key",
        default="/etc/mosquitto/certs/ca.key",
        help="Path to CA private key",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3650,
        help="Client cert validity days (default: 3650)",
    )
    parser.add_argument(
        "--kms-key-id",
        default="",
        help="Optional KMS key id/arn for SSE-KMS encryption in S3",
    )
    parser.add_argument("--country", default="IN")
    parser.add_argument("--state", default="Karnataka")
    parser.add_argument("--locality", default="Bengaluru")
    parser.add_argument("--org", default="Innofarm")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    missing = [p for p in [args.ca_crt, args.ca_key] if not pathlib.Path(p).exists()]
    if missing:
        raise FileNotFoundError(f"Missing CA files: {missing}")

    s3_client = boto3.client("s3", region_name=args.region)

    with tempfile.TemporaryDirectory(prefix="device-certs-") as tmp:
        work_dir = pathlib.Path(tmp)
        for device_id in args.device_ids:
            if "/" in device_id or not device_id.strip():
                raise ValueError(f"Invalid device_id: {device_id!r}")

            generate_device_cert(
                device_id=device_id,
                out_dir=work_dir,
                ca_crt_path=args.ca_crt,
                ca_key_path=args.ca_key,
                days=args.days,
                country=args.country,
                state=args.state,
                locality=args.locality,
                org=args.org,
            )

            device_crt_path = work_dir / f"{device_id}.crt"
            device_key_path = work_dir / f"{device_id}.key"

            upload_device_bundle(
                s3_client=s3_client,
                bucket=args.bucket,
                prefix=args.prefix,
                kms_key_id=args.kms_key_id,
                device_id=device_id,
                ca_crt_path=args.ca_crt,
                device_crt_path=device_crt_path,
                device_key_path=device_key_path,
                days=args.days,
            )

            print(
                f"Uploaded cert bundle for {device_id} to "
                f"s3://{args.bucket}/{args.prefix.rstrip('/')}/{device_id}/"
            )


if __name__ == "__main__":
    main()
