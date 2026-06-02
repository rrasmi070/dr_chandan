from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

from app.config import MONGODB_DB_NAME, MONGODB_URI


client = MongoClient(MONGODB_URI)
database = client[MONGODB_DB_NAME]


def get_db() -> Database:
    return database


def init_indexes(db: Database) -> None:
    db.services.create_index([("title", ASCENDING)], unique=True)
    db.cities.create_index([("name", ASCENDING)], unique=True)
    db.doctors.create_index([("employee_id", ASCENDING)], unique=True, sparse=True)
    db.doctors.create_index([("name", ASCENDING)])
    db.availability_slots.create_index([("doctor_id", ASCENDING), ("day_label", ASCENDING)])
    db.appointments.create_index([("created_at", DESCENDING)])
    db.reviews.create_index([("featured", ASCENDING), ("_id", DESCENDING)])
    db.admin_users.create_index([("username", ASCENDING)], unique=True)
    db.admin_users.create_index([("role", ASCENDING), ("active", ASCENDING)])
    db.employees.create_index([("employee_id", ASCENDING)], unique=True)
    db.employees.create_index([("user_id", ASCENDING)], unique=True)
    db.employees.create_index([("user_role", ASCENDING), ("is_active", ASCENDING)])
