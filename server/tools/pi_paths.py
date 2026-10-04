"""Shared paths for the Raspberry Pi native Linux deployment."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = PROJECT_ROOT / "server"
DATA_ROOT = Path(os.environ.get("RADAR_DATA_DIR", "/var/lib/kakao-radar")).expanduser()
STATE_ROOT = DATA_ROOT / ".state"
PRIVATE_ENV = Path(os.environ.get("RADAR_PRIVATE_ENV", "/etc/kakao-radar/credentials.env"))
DATABASE_URL = os.environ.get(
    "RADAR_DATABASE_URL",
    "postgresql:///radar?user=kakaoradar&host=/var/run/postgresql",
)
