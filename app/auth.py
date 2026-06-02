from __future__ import annotations

from fastapi import Request

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME


def normalize_role(role: str | None) -> str:
    normalized = (role or "admin").strip().lower()
    if normalized == "staff":
        return "staf"
    if normalized not in {"admin", "doctor", "reception", "staf"}:
        return "admin"
    return normalized


def authenticate(username: str, password: str) -> bool:
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD


def is_logged_in(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def get_user_role(request: Request) -> str:
    return normalize_role(str(request.session.get("role") or "admin"))


def is_doctor_user(request: Request) -> bool:
    return get_user_role(request) == "doctor"


def is_reception_user(request: Request) -> bool:
    return get_user_role(request) == "reception"


def is_staf_user(request: Request) -> bool:
    return get_user_role(request) == "staf"


def is_admin_user(request: Request) -> bool:
    return get_user_role(request) == "admin"


def get_linked_doctor_id(request: Request) -> str:
    return str(request.session.get("doctor_id") or "")


def has_permission(request: Request, permission_key: str) -> bool:
    if not is_admin_user(request):
        return False
    permissions = request.session.get("permissions") or {}
    return bool(permissions.get(permission_key, False))
