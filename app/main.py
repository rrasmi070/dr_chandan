from __future__ import annotations

from bson import ObjectId
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, BASE_DIR, DOCTOR_DOCUMENTS_DIR, DOCTOR_UPLOADS_DIR, EMPLOYEE_DOCUMENTS_DIR, REVIEW_UPLOADS_DIR, SECRET_KEY
from app.database import get_db, init_indexes
from app.repository import add_admin_user as add_admin_user_record
from app.repository import upsert_employee_for_user
from app.routers.admin import router as admin_router
from app.routers.public import router as public_router
from app.security import hash_password
from app.seed import seed_database


app = FastAPI(title="Physiophyte Medicare")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/uploads", StaticFiles(directory=str(BASE_DIR / "uploads")), name="uploads")


@app.on_event("startup")
def startup() -> None:
    DOCTOR_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    DOCTOR_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    EMPLOYEE_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

    db = get_db()
    init_indexes(db)
    seed_database(db)
    db.admin_users.update_many({"role": {"$exists": False}}, {"$set": {"role": "admin"}})

    default_username = ADMIN_USERNAME.strip().lower()
    existing_admin = db.admin_users.find_one({"username": default_username})
    if existing_admin and not existing_admin.get("password_hash"):
        db.admin_users.update_one(
            {"_id": existing_admin["_id"]},
            {
                "$set": {
                    "password_hash": hash_password(ADMIN_PASSWORD),
                    "permissions": existing_admin.get(
                        "permissions", {"can_add_doctor": True, "can_manage_admins": True}
                    ),
                    "role": existing_admin.get("role", "admin"),
                }
            },
        )
    elif not existing_admin:
        add_admin_user_record(
            db,
            ADMIN_USERNAME,
            hash_password(ADMIN_PASSWORD),
            permissions={"can_add_doctor": True, "can_manage_admins": True},
            active=True,
        )

    for user in db.admin_users.find():
        first_name = user.get("username", "user").strip().split(".")[0].title()
        last_name = "" if "." not in user.get("username", "") else user.get("username", "").strip().split(".")[-1].title()
        employee_payload = {
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name}".strip(),
            "dob": user.get("dob", ""),
            "joining_date": user.get("created_at", "").strftime("%Y-%m-%d") if user.get("created_at") else "",
            "designation": user.get("role", "admin").title(),
            "user_role": user.get("role", "admin"),
            "is_active": bool(user.get("active", True)),
            "username": user.get("username", ""),
            "documents": user.get("documents", []),
            "linked_doctor_id": str(user.get("doctor_id") or ""),
        }

        if user.get("role") == "doctor" and user.get("doctor_id"):
            doctor_ref = user.get("doctor_id")
            if isinstance(doctor_ref, str) and ObjectId.is_valid(doctor_ref):
                doctor_ref = ObjectId(doctor_ref)
            doctor = db.doctors.find_one({"_id": doctor_ref})
            if doctor and doctor.get("employee_id"):
                employee_payload["employee_id"] = doctor.get("employee_id")

        upsert_employee_for_user(
            db,
            str(user["_id"]),
            employee_payload,
        )


app.include_router(public_router)
app.include_router(admin_router)
