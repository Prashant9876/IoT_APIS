import os
import sys
from pathlib import Path

# Ensure project root is importable in all runners (local/CI/VM).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Test-safe defaults so app import does not fail.
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("MQTT_HOST", "localhost")
os.environ.setdefault("MQTT_PORT", "1883")
os.environ.setdefault("MQTT_USERNAME", "test-user")
os.environ.setdefault("MQTT_PASSWORD", "test-pass")
os.environ.setdefault("MQTT_TLS", "false")
os.environ.setdefault("MQTT_KEEPALIVE", "60")
os.environ.setdefault("SKIP_MQTT_CONNECT", "true")
