import json
import logging
import os
import threading
import time
import copy
from typing import Iterable, List
import boto3
import re
import psycopg2 
from datetime import datetime, timedelta, timezone
import pathlib

from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from fastapi import HTTPException
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID , ExtensionOID
from cryptography.hazmat.primitives.asymmetric import rsa, ec, padding
from cryptography.hazmat.primitives import hashes, serialization

from botocore.exceptions import BotoCoreError, ClientError

from dotenv import load_dotenv
from fastapi import HTTPException
import paho.mqtt.client as mqtt
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()



API_KEY = os.getenv("API_KEY")
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_TLS = os.getenv("MQTT_TLS", "false").lower() in ("true", "1", "yes")
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
SKIP_MQTT_CONNECT = os.getenv("SKIP_MQTT_CONNECT", "false").lower() in ("true", "1", "yes")


DBUSER = os.getenv("DBUSER", "")
DBSERVER = os.getenv("DBSERVER", "")
DBNAME = os.getenv("DBNAME", "")
DBPORT = int(os.getenv("DBPORT", "5432"))
DBSSL = os.getenv("DBSSL", "true").lower() in ("true", "1", "yes")
DBPASSWORD = os.getenv("DBPASSWORD", "")
DBTABLE = os.getenv("DBTABLE", "IoT_Device_IDS")

aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_region = os.getenv("AWS_DEFAULT_REGION")
secret_name = os.getenv("MQTT_CA_SECRET_NAME")
CERT_S3_BUCKET = os.getenv("CERT_S3_BUCKET")



# Create S3 client only once
s3_client = boto3.client(
    "s3",
    region_name=aws_region,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
)

IST = timezone(timedelta(hours=5, minutes=30))

if not API_KEY:
    raise RuntimeError("Server misconfigured: API_KEY missing in environment")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BackendMqttPublisher")


class MQTTClientWrapper:
    def __init__(
        self,
        host,
        port,
        username=None,
        password=None,
        tls=False,
        keepalive=60,
        start_loop=True,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.tls = tls
        self.keepalive = keepalive

        self.client = mqtt.Client()
        if self.username:
            self.client.username_pw_set(self.username, self.password)
        if self.tls:
            self.client.tls_set()

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        self.connected = False
        self._connect_lock = threading.Lock()
        if start_loop:
            self.client.loop_start()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logger.info("Connected to MQTT broker %s:%s", self.host, self.port)
        else:
            logger.error("Failed to connect to MQTT broker, rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        logger.warning("MQTT disconnected, rc=%s", rc)
        if rc != 0:
            logger.info("Scheduling reconnect to MQTT broker...")
            threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def connect(self):
        with self._connect_lock:
            while not self.connected:
                try:
                    self.client.connect(self.host, self.port, keepalive=self.keepalive)
                    break
                except Exception as e:
                    logger.error("Initial MQTT connect failed: %s. Retrying in 5s...", e)
                    time.sleep(5)

    def _reconnect_loop(self):
        with self._connect_lock:
            while not self.connected:
                try:
                    self.client.reconnect()
                    logger.info("Reconnected to MQTT broker")
                    break
                except Exception as e:
                    logger.error("Reconnect failed, retrying in 5 seconds: %s", e)
                    time.sleep(5)

    def publish(self, topic, payload, qos=1, retain=False):
        payload_str = json.dumps(payload, default=str)
        if self.connected:
            self.client.publish(topic, payload_str, qos=qos, retain=retain)
        else:
            logger.warning("MQTT not connected, cannot publish to topic %s", topic)


mqtt_client = MQTTClientWrapper(
    host=MQTT_HOST,
    port=MQTT_PORT,
    username=MQTT_USERNAME,
    password=MQTT_PASSWORD,
    tls=MQTT_TLS,
    keepalive=MQTT_KEEPALIVE,
    start_loop=not SKIP_MQTT_CONNECT,
)

if not SKIP_MQTT_CONNECT:
    mqtt_client.connect()


def validate_api_key(x_api_key: str):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


def require_keys(payload: dict, keys: Iterable[str], message: str):
    if not all(k in payload for k in keys):
        raise HTTPException(status_code=400, detail=message)



def get_mqtt_topic(payload: dict):
    farm_id = payload.get("FarmID")
    dn = payload.get("DN")
    if not farm_id or not dn:
        raise ValueError("Missing required keys: FarmID or DN")
    if dn == "IDC":
        return f"farm/{farm_id}/IIrrigation"
    if dn in {"FU", "FUD"}:
        return f"farm/{farm_id}/fertigation"
    return f"farm/{farm_id}/SSub"


def publish_and_response(payload: dict):
    topic = get_mqtt_topic(payload)
    
    farm_id = payload.get("FarmID")
    API_Topic = f"farm/{farm_id}/api"

    payload["Mqtt_topic"] = topic
    mqtt_client.publish(API_Topic, payload)
    clean_payload = copy.deepcopy(payload)
    clean_payload.pop("meta", None)
    clean_payload.pop("Mqtt_topic", None)

    mqtt_client.publish(topic, clean_payload)

    logger.info("Published to topic %s: %s", topic, json.dumps(payload))
    return {"status": "accepted", "topic": topic, "payload": payload}





class GenerateCertificateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    csr_pem: str = Field(..., alias="csr_pem")
    farm_id: str = Field(..., alias="farmID")
    Device_Id: str = Field(..., alias="Device_Id")
    dry_run: bool = Field(False, alias="dry_run")       # simple api check 





def  validate_device_IDS(device_id: str):
    global DBUSER, DBSERVER, DBNAME, DBPORT, DBSSL, DBPASSWORD, DBTABLE
    try:
        conn = psycopg2.connect(
            user=DBUSER,
            password=DBPASSWORD,
            host=DBSERVER,
            port=DBPORT,
            database=DBNAME,
            sslmode="require" if DBSSL else "disable"   # because DBSSL=true
        )

        query = sql.SQL("""
            SELECT
                certificate_assigned,
                certificate_assigned_at
            FROM {table}
            WHERE "DeviceId" = %s
            LIMIT 1;
        """).format(
            table=sql.Identifier(DBTABLE)
        )

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (device_id,))
            result = cursor.fetchone()

        conn.close()

        if not result:
            return {
                "status": False,
                "message": "Device_ID not found",
                "Device_ID": device_id,
                "certificate_assigned": None,
                "certificate_assigned_at": None
            }

        return {
            "status": True,
            "Device_ID": device_id,
            "certificate_assigned": result["certificate_assigned"],
            "certificate_assigned_at": result["certificate_assigned_at"]
        }

    except Exception as e:
        return {
            "status": False,
            "message": "Database error",
            "error": str(e)
        }



def update_certificate_assigned(device_id: str):
    global DBUSER, DBSERVER, DBNAME, DBPORT, DBSSL, DBPASSWORD, DBTABLE

    try:
        assigned_at_ist = datetime.now(IST)

        conn = psycopg2.connect(
            user=DBUSER,
            password=DBPASSWORD,
            host=DBSERVER,
            port=DBPORT,
            database=DBNAME,
            sslmode="require" if DBSSL else "disable"
        )

        query = sql.SQL("""
            UPDATE {table}
            SET 
                certificate_assigned = %s,
                certificate_assigned_at = %s
            WHERE "DeviceId" = %s
            RETURNING 
                "DeviceId",
                certificate_assigned,
                certificate_assigned_at;
        """).format(
            table=sql.Identifier(DBTABLE)
        )

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                query,
                (
                    True,
                    assigned_at_ist,
                    device_id
                )
            )

            result = cursor.fetchone()

        conn.commit()
        conn.close()

        if not result:
            return {
                "success": False,
                "found": False,
                "code": "DEVICE_NOT_FOUND",
                "message": "Device_ID not found, update not done",
                "Device_ID": device_id
            }

        return {
            "success": True,
            "found": True,
            "code": "CERTIFICATE_UPDATED",
            "message": "Certificate assignment updated successfully",
            "Device_ID": result["DeviceId"],
            "certificate_assigned": result["certificate_assigned"],
            "certificate_assigned_at": result["certificate_assigned_at"]
        }

    except Exception as e:
        return {
            "success": False,
            "found": None,
            "code": "DB_ERROR",
            "message": "Database error while updating certificate assignment",
            "error": str(e)
        }



def validate_device_csr(csr_pem: str, device_id: str):
    DEVICE_ID_RE = re.compile(r"^IF[A-Z0-9]+$")


    if not csr_pem or not csr_pem.strip():
        raise HTTPException(status_code=400, detail="csr_pem is required")

    csr_pem = csr_pem.strip()

    if "-----BEGIN CERTIFICATE REQUEST-----" not in csr_pem:
        raise HTTPException(
            status_code=400,
            detail="Invalid csr_pem: missing BEGIN CERTIFICATE REQUEST header",
        )

    if "-----END CERTIFICATE REQUEST-----" not in csr_pem:
        raise HTTPException(
            status_code=400,
            detail="Invalid csr_pem: missing END CERTIFICATE REQUEST footer",
        )

    if not device_id or not device_id.strip():
        raise HTTPException(status_code=400, detail="Device_Id is required")

    device_id = device_id.strip()

    if not DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=400, detail="Invalid Device_Id format")

    try:
        csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid csr_pem: cannot parse CSR")

    if not csr.is_signature_valid:
        raise HTTPException(status_code=400, detail="Invalid CSR signature")

    cn_attrs = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)

    if not cn_attrs:
        raise HTTPException(status_code=400, detail="CSR Common Name is required")

    csr_cn = cn_attrs[0].value

    if csr_cn != device_id:
        raise HTTPException(
            status_code=400,
            detail=f"CSR CN mismatch. Expected {device_id}, got {csr_cn}",
        )

    public_key = csr.public_key()

    if isinstance(public_key, rsa.RSAPublicKey):
        if public_key.key_size < 2048:
            raise HTTPException(
                status_code=400,
                detail="RSA key must be at least 2048 bits",
            )

    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        allowed_curves = {"secp256r1", "prime256v1"}

        if public_key.curve.name not in allowed_curves:
            raise HTTPException(
                status_code=400,
                detail="Only EC P-256 key is allowed",
            )

    else:
        raise HTTPException(status_code=400, detail="Unsupported public key type")

    return csr


def get_mqtt_ca_from_secrets_manager():
    global aws_access_key_id, aws_secret_access_key, aws_region, secret_name

    if not aws_access_key_id:
        raise HTTPException(status_code=500, detail="AWS_ACCESS_KEY_ID missing in .env")

    if not aws_secret_access_key:
        raise HTTPException(status_code=500, detail="AWS_SECRET_ACCESS_KEY missing in .env")

    try:
        session = boto3.Session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=aws_region,
        )

        client = session.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_name)
        secret = json.loads(response["SecretString"])

        root_ca_key = secret.get("rootCA.key")
        root_ca_pem = secret.get("rootCA.pem")

        if not root_ca_key:
            raise HTTPException(status_code=500, detail="rootCA.key not found in AWS secret")

        if not root_ca_pem:
            raise HTTPException(status_code=500, detail="rootCA.pem not found in AWS secret")

        return root_ca_key, root_ca_pem

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load CA from AWS Secrets Manager: {str(e)}",
        )


def generate_device_certificate_from_csr(
    csr_pem: str,
    device_id: str,
    valid_days: int = 3650,
):
    root_ca_key_pem, root_ca_pem = get_mqtt_ca_from_secrets_manager()

    try:
        csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))

        root_ca_key = serialization.load_pem_private_key(
            root_ca_key_pem.encode("utf-8"),
            password=None,
        )

        root_ca_cert = x509.load_pem_x509_certificate(
            root_ca_pem.encode("utf-8")
        )

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid CSR or CA certificate data: {str(e)}",
        )

    now = datetime.now(timezone.utc)

    try:
        device_cert = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(root_ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=valid_days))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
            .sign(
                private_key=root_ca_key,
                algorithm=hashes.SHA256(),
            )
        )

        device_crt = device_cert.public_bytes(
            serialization.Encoding.PEM
        ).decode("utf-8")

        return {
            "device_id": device_id,
            "device_crt": device_crt,
            "serial_number": str(device_cert.serial_number),
            "valid_from": device_cert.not_valid_before_utc.isoformat(),
            "valid_until": device_cert.not_valid_after_utc.isoformat(),
            "issuer": device_cert.issuer.rfc4514_string(),
            "subject": device_cert.subject.rfc4514_string(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not generate device certificate: {str(e)}",
        )
    


def verify_generated_device_cert(
    device_crt_pem: str,
    csr_pem: str,
    root_ca_pem: str,
    expected_device_id: str,
):
    try:
        device_cert = x509.load_pem_x509_certificate(device_crt_pem.encode("utf-8"))
        csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
        root_ca_cert = x509.load_pem_x509_certificate(root_ca_pem.encode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Certificate parse failed: {str(e)}")

    now = datetime.now(timezone.utc)

    if now < device_cert.not_valid_before_utc:
        raise HTTPException(status_code=500, detail="Generated certificate is not valid yet")

    if now > device_cert.not_valid_after_utc:
        raise HTTPException(status_code=500, detail="Generated certificate is already expired")

    cn_attrs = device_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)

    if not cn_attrs:
        raise HTTPException(status_code=500, detail="Generated certificate CN missing")

    cert_cn = cn_attrs[0].value

    if cert_cn != expected_device_id:
        raise HTTPException(
            status_code=500,
            detail=f"Generated certificate CN mismatch. Expected {expected_device_id}, got {cert_cn}",
        )

    if device_cert.issuer != root_ca_cert.subject:
        raise HTTPException(status_code=500, detail="Generated certificate issuer does not match root CA")

    ca_public_key = root_ca_cert.public_key()

    try:
        if isinstance(ca_public_key, ec.EllipticCurvePublicKey):
            ca_public_key.verify(
                device_cert.signature,
                device_cert.tbs_certificate_bytes,
                ec.ECDSA(device_cert.signature_hash_algorithm),
            )
        else:
            ca_public_key.verify(
                device_cert.signature,
                device_cert.tbs_certificate_bytes,
                padding.PKCS1v15(),
                device_cert.signature_hash_algorithm,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Certificate signature verification failed: {str(e)}")

    cert_public_key_pem = device_cert.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    csr_public_key_pem = csr.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    if cert_public_key_pem != csr_public_key_pem:
        raise HTTPException(status_code=500, detail="Certificate public key does not match CSR public key")

    try:
        eku = device_cert.extensions.get_extension_for_oid(
            ExtensionOID.EXTENDED_KEY_USAGE
        ).value

        if ExtendedKeyUsageOID.CLIENT_AUTH not in eku:
            raise HTTPException(status_code=500, detail="Generated certificate is not valid for client auth")

    except x509.ExtensionNotFound:
        raise HTTPException(status_code=500, detail="Generated certificate missing Extended Key Usage")

    try:
        basic_constraints = device_cert.extensions.get_extension_for_oid(
            ExtensionOID.BASIC_CONSTRAINTS
        ).value

        if basic_constraints.ca is True:
            raise HTTPException(status_code=500, detail="Generated device certificate must not be a CA certificate")

    except x509.ExtensionNotFound:
        raise HTTPException(status_code=500, detail="Generated certificate missing Basic Constraints")

    return True


def upload_device_crt_to_s3(
    farm_id: str,
    payload: dict,
):
    """
    Upload device_crt from payload directly to S3.

    S3 path format:
    farm_id/device_id_timestamp/device_id_timestamp.crt
    """

    try:
        farm_id = farm_id.strip()

        if not farm_id:
            return {
                "success": False,
                "message": "farm_id is required"
            }

        if "/" in farm_id:
            return {
                "success": False,
                "message": "farm_id must not contain '/'"
            }

        device_id = payload.get("device_id")
        device_crt = payload.get("device_crt")

        if not device_id:
            return {
                "success": False,
                "message": "device_id is missing in payload"
            }

        if "/" in device_id:
            return {
                "success": False,
                "message": "device_id must not contain '/'"
            }

        if not device_crt:
            return {
                "success": False,
                "message": "device_crt is missing in payload"
            }

        if "-----BEGIN CERTIFICATE-----" not in device_crt:
            return {
                "success": False,
                "message": "Invalid device_crt: missing BEGIN CERTIFICATE"
            }

        if "-----END CERTIFICATE-----" not in device_crt:
            return {
                "success": False,
                "message": "Invalid device_crt: missing END CERTIFICATE"
            }

        timestamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")

        file_name = f"{device_id}_{timestamp}.crt"
        s3_key = f"{farm_id}/{device_id}_{timestamp}/{file_name}"

        s3_client.put_object(
            Bucket=CERT_S3_BUCKET,
            Key=s3_key,
            Body=device_crt.encode("utf-8"),
            ContentType="application/x-pem-file",
            ServerSideEncryption="AES256"
        )

        return {
            "success": True,
            "message": "Device certificate uploaded successfully",
            "farmID": farm_id,
            "device_id": device_id,
            "timestamp_ist": timestamp,
            "s3_key": s3_key,
            "s3_path": f"s3://{CERT_S3_BUCKET}/{s3_key}"
        }

    except (ClientError, BotoCoreError) as e:
        return {
            "success": False,
            "message": "S3 upload failed",
            "error": str(e)
        }

    except Exception as e:
        return {
            "success": False,
            "message": "Unexpected error",
            "error": str(e)
        }