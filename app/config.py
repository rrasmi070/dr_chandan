from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
UPLOADS_DIR = BASE_DIR / "uploads"
DOCTOR_UPLOADS_DIR = UPLOADS_DIR / "doctors"
DOCTOR_DOCUMENTS_DIR = UPLOADS_DIR / "doctor-documents"
REVIEW_UPLOADS_DIR = UPLOADS_DIR / "reviews"
EMPLOYEE_DOCUMENTS_DIR = UPLOADS_DIR / "employee-documents"


def get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


SECRET_KEY = get_env("SECRET_KEY", "change-me-for-production")
ADMIN_USERNAME = get_env("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = get_env("ADMIN_PASSWORD", "admin123")
MONGODB_URI = (
    os.getenv("MONGODB_URI")
    or os.getenv("conection_str")
    or "mongodb://127.0.0.1:27017/"
)
MONGODB_DB_NAME = get_env("MONGODB_DB_NAME", "physiophyte_medicare")
WHATSAPP_PROVIDER = get_env("WHATSAPP_PROVIDER", "disabled")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_NUMBER = os.getenv("WHATSAPP_ACCESS_NUMBER", "")
