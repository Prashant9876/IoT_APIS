import json
import logging
import os
import threading
import time
from typing import Iterable

from dotenv import load_dotenv
from fastapi import HTTPException
import paho.mqtt.client as mqtt

load_dotenv()

API_KEY = os.getenv("API_KEY")
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_TLS = os.getenv("MQTT_TLS", "false").lower() in ("true", "1", "yes")
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
SKIP_MQTT_CONNECT = os.getenv("SKIP_MQTT_CONNECT", "false").lower() in ("true", "1", "yes")

if not API_KEY:
    raise RuntimeError("Server misconfigured: API_KEY missing in environment")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BackendMqttPublisher")


class MQTTClientWrapper:
    def __init__(self, host, port, username=None, password=None, tls=False, keepalive=60):
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
    if dn == "FU":
        return f"farm/{farm_id}/fertigation"
    return f"farm/{farm_id}/SSub"


def publish_and_response(payload: dict):
    topic = get_mqtt_topic(payload)
    mqtt_client.publish(topic, payload)
    logger.info("Published to topic %s: %s", topic, json.dumps(payload))
    return {"status": "accepted", "topic": topic, "payload": payload}
