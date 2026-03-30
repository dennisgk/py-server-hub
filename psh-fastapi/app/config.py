from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SERVICES_DIR = DATA_DIR / "services"
LOGS_DIR = DATA_DIR / "logs"
TMP_DIR = DATA_DIR / "tmp"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "psh.sqlite3"

JWT_SECRET = os.getenv("PSH_JWT_SECRET", "replace-this-in-production")
JWT_EXPIRE_MINUTES = int(os.getenv("PSH_JWT_EXPIRE_MINUTES", "480"))
DEFAULT_USERNAME = os.getenv("PSH_DEFAULT_USERNAME", "admin")
DEFAULT_PASSWORD = os.getenv("PSH_DEFAULT_PASSWORD", "admin123!")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
