from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil
import re

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.database import Database


def _normalize_page(page: int) -> int:
    return page if page > 0 else 1


def _normalize_per_page(per_page: int, *, default: int = 10, max_value: int = 100) -> int:
    if per_page <= 0:
        return default
    return min(per_page, max_value)


def _build_paged_result(items: list[dict], total_items: int, page: int, per_page: int) -> dict:
    total_pages = max(1, ceil(total_items / per_page)) if total_items else 1
    current_page = min(page, total_pages)
    return {
        "items": items,
        "page": current_page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": current_page > 1,
        "has_next": current_page < total_pages,
        "prev_page": current_page - 1 if current_page > 1 else 1,
        "next_page": current_page + 1 if current_page < total_pages else total_pages,
    }


def _parse_date_range(start_date: str | None = None, end_date: str | None = None) -> dict:
    filters: dict[str, dict] = {}
    created_at_filter: dict[str, datetime] = {}

    if start_date:
        created_at_filter["$gte"] = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        created_at_filter["$lt"] = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

    if created_at_filter:
        filters["created_at"] = created_at_filter
    return filters


def _serialize(document: dict | None) -> dict | None:
    if not document:
        return None

    serialized = dict(document)
    serialized["id"] = str(serialized.pop("_id"))
    if "doctor_id" in serialized and serialized["doctor_id"] is not None:
        serialized["doctor_id"] = str(serialized["doctor_id"])
    if "user_id" in serialized and serialized["user_id"] is not None:
        serialized["user_id"] = str(serialized["user_id"])
    if "completed_by_doctor_id" in serialized and serialized["completed_by_doctor_id"] is not None:
        serialized["completed_by_doctor_id"] = str(serialized["completed_by_doctor_id"])
    history_entries = serialized.get("history") or []
    normalized_history: list[dict] = []
    for entry in history_entries:
        item = dict(entry)
        if item.get("doctor_id") is not None:
            item["doctor_id"] = str(item["doctor_id"])
        normalized_history.append(item)
    serialized["history"] = normalized_history
    return serialized


def _object_id(value: str | ObjectId | None) -> ObjectId | None:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(value):
        return None
    return ObjectId(value)


def list_services(db: Database) -> list[dict]:
    return [_serialize(service) for service in db.services.find().sort("title", 1)]


def add_service(db: Database, title: str, description: str) -> str | None:
    normalized = title.strip()
    if not normalized:
        return None
    if db.services.find_one({"title": normalized}):
        return None
    result = db.services.insert_one({"title": normalized, "description": description.strip()})
    return str(result.inserted_id)


def update_service(db: Database, service_id: str, title: str, description: str) -> bool:
    object_id = _object_id(service_id)
    if not object_id:
        return False

    result = db.services.update_one(
        {"_id": object_id},
        {"$set": {"title": title.strip(), "description": description.strip()}},
    )
    return result.matched_count > 0


def list_cities(db: Database) -> list[dict]:
    return [_serialize(city) for city in db.cities.find().sort("name", 1)]


def add_city(db: Database, name: str) -> str | None:
    normalized = name.strip()
    if not normalized:
        return None
    if db.cities.find_one({"name": {"$regex": f"^{normalized}$", "$options": "i"}}):
        return None
    result = db.cities.insert_one({"name": normalized})
    return str(result.inserted_id)


def update_city(db: Database, city_id: str, name: str) -> bool:
    object_id = _object_id(city_id)
    if not object_id:
        return False

    result = db.cities.update_one({"_id": object_id}, {"$set": {"name": name.strip()}})
    return result.matched_count > 0


def list_reviews(db: Database, *, featured_only: bool = False) -> list[dict]:
    query = {"featured": True} if featured_only else {}
    return [_serialize(review) for review in db.reviews.find(query).sort("_id", DESCENDING)]


def list_reviews_page(db: Database, *, page: int = 1, per_page: int = 10) -> dict:
    page = _normalize_page(page)
    per_page = _normalize_per_page(per_page)
    total_items = db.reviews.count_documents({})
    cursor = db.reviews.find().sort("_id", DESCENDING).skip((page - 1) * per_page).limit(per_page)
    items = [_serialize(review) for review in cursor]
    return _build_paged_result(items, total_items, page, per_page)


def list_doctors(db: Database, *, active_only: bool = False) -> list[dict]:
    query = {"active": True} if active_only else {}
    doctors = [_serialize(doctor) for doctor in db.doctors.find(query).sort("_id", DESCENDING)]
    doctor_ids = [doctor["id"] for doctor in doctors]
    slots_by_doctor: dict[str, list[dict]] = {doctor_id: [] for doctor_id in doctor_ids}

    if doctor_ids:
        valid_object_ids = [_object_id(doctor_id) for doctor_id in doctor_ids]
        valid_object_ids = [object_id for object_id in valid_object_ids if object_id]
        for slot in db.availability_slots.find({"doctor_id": {"$in": valid_object_ids}}).sort([("day_label", 1), ("time_range", 1)]):
            serialized_slot = _serialize(slot)
            slot_doctor_id = str(slot["doctor_id"])
            slots_by_doctor.setdefault(slot_doctor_id, []).append(serialized_slot)

    for doctor in doctors:
        doctor["availability_slots"] = slots_by_doctor.get(doctor["id"], [])

    return doctors


def list_doctors_page(db: Database, *, page: int = 1, per_page: int = 10, active_only: bool = False) -> dict:
    page = _normalize_page(page)
    per_page = _normalize_per_page(per_page)
    query = {"active": True} if active_only else {}
    total_items = db.doctors.count_documents(query)
    doctors = [
        _serialize(doctor)
        for doctor in db.doctors.find(query).sort("_id", DESCENDING).skip((page - 1) * per_page).limit(per_page)
    ]
    doctor_ids = [doctor["id"] for doctor in doctors]
    slots_by_doctor: dict[str, list[dict]] = {doctor_id: [] for doctor_id in doctor_ids}

    if doctor_ids:
        valid_object_ids = [_object_id(doctor_id) for doctor_id in doctor_ids]
        valid_object_ids = [object_id for object_id in valid_object_ids if object_id]
        for slot in db.availability_slots.find({"doctor_id": {"$in": valid_object_ids}}).sort([("day_label", 1), ("time_range", 1)]):
            serialized_slot = _serialize(slot)
            slot_doctor_id = str(slot["doctor_id"])
            slots_by_doctor.setdefault(slot_doctor_id, []).append(serialized_slot)

    for doctor in doctors:
        doctor["availability_slots"] = slots_by_doctor.get(doctor["id"], [])

    return _build_paged_result(doctors, total_items, page, per_page)


def _hydrate_appointments(db: Database, appointments: list[dict]) -> list[dict]:
    doctor_ids = {appointment["doctor_id"] for appointment in appointments if appointment.get("doctor_id")}
    doctor_map: dict[str, dict] = {}

    if doctor_ids:
        valid_object_ids = [_object_id(doctor_id) for doctor_id in doctor_ids]
        valid_object_ids = [object_id for object_id in valid_object_ids if object_id]
        for doctor in db.doctors.find({"_id": {"$in": valid_object_ids}}):
            serialized_doctor = _serialize(doctor)
            doctor_map[serialized_doctor["id"]] = serialized_doctor

    for appointment in appointments:
        appointment["doctor"] = doctor_map.get(appointment.get("doctor_id"))

        history = appointment.get("history") or []
        for item in history:
            if item.get("doctor_id"):
                item["doctor"] = doctor_map.get(item["doctor_id"])

    return appointments


def _append_appointment_history(
    db: Database,
    appointment_object_id: ObjectId,
    *,
    action: str,
    actor_username: str,
    actor_role: str,
    changes: dict,
) -> None:
    db.appointments.update_one(
        {"_id": appointment_object_id},
        {
            "$push": {
                "history": {
                    "created_at": datetime.utcnow(),
                    "action": action,
                    "actor_username": actor_username,
                    "actor_role": actor_role,
                    "changes": changes,
                }
            }
        },
    )


def _hydrate_admin_users(db: Database, admin_users: list[dict]) -> list[dict]:
    doctor_ids = {admin["doctor_id"] for admin in admin_users if admin.get("doctor_id")}
    doctor_map: dict[str, dict] = {}

    if doctor_ids:
        valid_object_ids = [_object_id(doctor_id) for doctor_id in doctor_ids]
        valid_object_ids = [object_id for object_id in valid_object_ids if object_id]
        for doctor in db.doctors.find({"_id": {"$in": valid_object_ids}}):
            serialized_doctor = _serialize(doctor)
            doctor_map[serialized_doctor["id"]] = serialized_doctor

    for admin in admin_users:
        admin["assigned_doctor"] = doctor_map.get(admin.get("doctor_id"))

    user_ids = [admin["id"] for admin in admin_users]
    employee_map: dict[str, dict] = {}
    if user_ids:
        valid_user_object_ids = [_object_id(user_id) for user_id in user_ids]
        valid_user_object_ids = [object_id for object_id in valid_user_object_ids if object_id]
        for employee in db.employees.find({"user_id": {"$in": valid_user_object_ids}}):
            serialized_employee = _serialize(employee)
            if serialized_employee and serialized_employee.get("user_id"):
                employee_map[serialized_employee["user_id"]] = serialized_employee

    for admin in admin_users:
        admin["employee"] = employee_map.get(admin["id"])

    return admin_users


def list_appointments(db: Database) -> list[dict]:
    appointments = [_serialize(appointment) for appointment in db.appointments.find().sort("created_at", DESCENDING)]
    return _hydrate_appointments(db, appointments)


def list_appointments_page(
    db: Database,
    *,
    page: int = 1,
    per_page: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
    doctor_id: str | None = None,
    search_term: str | None = None,
) -> dict:
    page = _normalize_page(page)
    per_page = _normalize_per_page(per_page)
    query = _parse_date_range(start_date, end_date)
    if doctor_id:
        object_id = _object_id(doctor_id)
        if object_id:
            query["doctor_id"] = object_id
        else:
            return _build_paged_result([], 0, page, per_page)
    if search_term and search_term.strip():
        safe_term = re.escape(search_term.strip())
        query["$or"] = [
            {"patient_name": {"$regex": safe_term, "$options": "i"}},
            {"phone": {"$regex": safe_term, "$options": "i"}},
        ]

    total_items = db.appointments.count_documents(query)
    cursor = db.appointments.find(query).sort("created_at", DESCENDING).skip((page - 1) * per_page).limit(per_page)
    items = [_serialize(appointment) for appointment in cursor]
    items = _hydrate_appointments(db, items)
    return _build_paged_result(items, total_items, page, per_page)


def list_appointments_for_export(
    db: Database,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    doctor_id: str | None = None,
    search_term: str | None = None,
) -> list[dict]:
    query = _parse_date_range(start_date, end_date)
    if doctor_id:
        object_id = _object_id(doctor_id)
        if not object_id:
            return []
        query["doctor_id"] = object_id
    if search_term and search_term.strip():
        safe_term = re.escape(search_term.strip())
        query["$or"] = [
            {"patient_name": {"$regex": safe_term, "$options": "i"}},
            {"phone": {"$regex": safe_term, "$options": "i"}},
        ]
    appointments = [_serialize(appointment) for appointment in db.appointments.find(query).sort("created_at", DESCENDING)]
    return _hydrate_appointments(db, appointments)


def get_appointment(db: Database, appointment_id: str) -> dict | None:
    object_id = _object_id(appointment_id)
    if not object_id:
        return None
    appointment = db.appointments.find_one({"_id": object_id})
    if not appointment:
        return None
    items = _hydrate_appointments(db, [_serialize(appointment)])
    return items[0] if items else None


def create_appointment(db: Database, payload: dict) -> str:
    document = {
        **payload,
        "doctor_id": _object_id(payload["doctor_id"]) if payload.get("doctor_id") else None,
        "status": "Pending",
        "payment_status": "Pending",
        "payment_details": "",
        "history": [],
        "created_at": datetime.utcnow(),
    }
    result = db.appointments.insert_one(document)
    return str(result.inserted_id)


def add_doctor(db: Database, payload: dict) -> str:
    counter = db.counters.find_one_and_update(
        {"_id": "doctor_employee_id"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    employee_id = f"DOC-{counter['seq']:04d}"
    document = {**payload, "employee_id": employee_id}
    result = db.doctors.insert_one(document)
    return str(result.inserted_id)


def update_doctor(db: Database, doctor_id: str, payload: dict) -> bool:
    object_id = _object_id(doctor_id)
    if not object_id:
        return False

    result = db.doctors.update_one({"_id": object_id}, {"$set": payload})
    return result.matched_count > 0


def add_availability(db: Database, payload: dict) -> str | None:
    doctor_id = _object_id(payload["doctor_id"])
    if not doctor_id:
        return None

    result = db.availability_slots.insert_one(
        {
            "doctor_id": doctor_id,
            "day_label": payload["day_label"],
            "time_range": payload["time_range"],
        }
    )
    return str(result.inserted_id)


def update_doctor_status(db: Database, doctor_id: str, active: bool) -> bool:
    object_id = _object_id(doctor_id)
    if not object_id:
        return False

    result = db.doctors.update_one({"_id": object_id}, {"$set": {"active": active}})
    return result.matched_count > 0


def get_admin_by_username(db: Database, username: str) -> dict | None:
    admin = _serialize(db.admin_users.find_one({"username": username.strip().lower(), "active": True}))
    if not admin:
        return None
    users = _hydrate_admin_users(db, [admin])
    return users[0] if users else None


def get_admin_for_login(db: Database, identifier: str, role: str) -> dict | None:
    normalized_identifier = identifier.strip()
    if not normalized_identifier:
        return None

    normalized_role = role.strip().lower()
    username_match = _serialize(
        db.admin_users.find_one(
            {
                "username": normalized_identifier.lower(),
                "role": normalized_role,
                "active": True,
            }
        )
    )
    if username_match:
        users = _hydrate_admin_users(db, [username_match])
        return users[0] if users else None

    employee = _serialize(db.employees.find_one({"employee_id": normalized_identifier.upper(), "is_active": True}))
    if not employee:
        employee = _serialize(
            db.employees.find_one(
                {
                    "employee_id": {"$regex": f"^{re.escape(normalized_identifier)}$", "$options": "i"},
                    "is_active": True,
                }
            )
        )
    if not employee or not employee.get("user_id"):
        return None

    user_object_id = _object_id(employee["user_id"])
    if not user_object_id:
        return None

    admin = _serialize(
        db.admin_users.find_one(
            {
                "_id": user_object_id,
                "role": normalized_role,
                "active": True,
            }
        )
    )
    if not admin:
        return None

    users = _hydrate_admin_users(db, [admin])
    return users[0] if users else None


def list_admin_users(db: Database, *, include_admin_role: bool = True) -> list[dict]:
    query = {} if include_admin_role else {"role": {"$ne": "admin"}}
    items = [_serialize(admin) for admin in db.admin_users.find(query).sort("username", 1)]
    return _hydrate_admin_users(db, items)


def list_admin_users_page(
    db: Database,
    *,
    page: int = 1,
    per_page: int = 10,
    include_admin_role: bool = True,
) -> dict:
    page = _normalize_page(page)
    per_page = _normalize_per_page(per_page)
    query = {} if include_admin_role else {"role": {"$ne": "admin"}}
    total_items = db.admin_users.count_documents(query)
    cursor = db.admin_users.find(query).sort("username", 1).skip((page - 1) * per_page).limit(per_page)
    items = [_serialize(admin) for admin in cursor]
    items = _hydrate_admin_users(db, items)
    return _build_paged_result(items, total_items, page, per_page)


def _hydrate_employees(db: Database, employees: list[dict]) -> list[dict]:
    user_ids = {employee.get("user_id") for employee in employees if employee.get("user_id")}
    user_map: dict[str, dict] = {}

    if user_ids:
        valid_user_object_ids = [_object_id(user_id) for user_id in user_ids]
        valid_user_object_ids = [object_id for object_id in valid_user_object_ids if object_id]
        for user in db.admin_users.find({"_id": {"$in": valid_user_object_ids}}):
            serialized_user = _serialize(user)
            user_map[serialized_user["id"]] = serialized_user

    doctor_ids = {employee.get("linked_doctor_id") for employee in employees if employee.get("linked_doctor_id")}
    for employee in employees:
        linked_user = user_map.get(employee.get("user_id", ""))
        if linked_user and linked_user.get("doctor_id"):
            doctor_ids.add(linked_user["doctor_id"])

    doctor_map: dict[str, dict] = {}
    if doctor_ids:
        valid_doctor_object_ids = [_object_id(doctor_id) for doctor_id in doctor_ids]
        valid_doctor_object_ids = [object_id for object_id in valid_doctor_object_ids if object_id]
        for doctor in db.doctors.find({"_id": {"$in": valid_doctor_object_ids}}):
            serialized_doctor = _serialize(doctor)
            doctor_map[serialized_doctor["id"]] = serialized_doctor

    for employee in employees:
        linked_user = user_map.get(employee.get("user_id", ""))
        employee["user"] = linked_user
        linked_doctor_id = employee.get("linked_doctor_id") or (linked_user.get("doctor_id") if linked_user else "")
        employee["linked_doctor"] = doctor_map.get(linked_doctor_id)

    return employees


def list_employees_page(
    db: Database,
    *,
    page: int = 1,
    per_page: int = 10,
    search_term: str | None = None,
    designation: str | None = None,
    include_admin_role: bool = True,
) -> dict:
    page = _normalize_page(page)
    per_page = _normalize_per_page(per_page)
    query = _employee_query(
        search_term=search_term,
        designation=designation,
        include_admin_role=include_admin_role,
    )

    total_items = db.employees.count_documents(query)
    cursor = db.employees.find(query).sort("created_at", DESCENDING).skip((page - 1) * per_page).limit(per_page)
    items = [_serialize(employee) for employee in cursor]
    items = _hydrate_employees(db, items)
    return _build_paged_result(items, total_items, page, per_page)


def get_employee_detail(db: Database, employee_id: str, *, include_admin_role: bool = True) -> dict | None:
    object_id = _object_id(employee_id)
    if not object_id:
        return None

    query: dict = {"_id": object_id}
    if not include_admin_role:
        query["user_role"] = {"$ne": "admin"}

    employee = _serialize(db.employees.find_one(query))
    if not employee:
        return None

    hydrated = _hydrate_employees(db, [employee])
    return hydrated[0] if hydrated else None


def _employee_query(
    *,
    search_term: str | None = None,
    designation: str | None = None,
    include_admin_role: bool = True,
) -> dict:
    conditions: list[dict] = []

    if not include_admin_role:
        conditions.append({"user_role": {"$ne": "admin"}})

    if search_term and search_term.strip():
        safe_term = re.escape(search_term.strip())
        conditions.append(
            {
                "$or": [
                    {"phone": {"$regex": safe_term, "$options": "i"}},
                    {"full_name": {"$regex": safe_term, "$options": "i"}},
                    {"first_name": {"$regex": safe_term, "$options": "i"}},
                    {"last_name": {"$regex": safe_term, "$options": "i"}},
                    {"designation": {"$regex": safe_term, "$options": "i"}},
                ]
            }
        )

    if designation and designation.strip():
        safe_designation = re.escape(designation.strip())
        conditions.append({"designation": {"$regex": f"^{safe_designation}$", "$options": "i"}})

    if not conditions:
        return {}
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def list_employee_designations(db: Database, *, include_admin_role: bool = True) -> list[str]:
    query = _employee_query(include_admin_role=include_admin_role)
    values = db.employees.distinct("designation", query)
    cleaned = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    return sorted(set(cleaned), key=str.lower)


def list_employees_for_export(
    db: Database,
    *,
    search_term: str | None = None,
    designation: str | None = None,
    include_admin_role: bool = True,
) -> list[dict]:
    query = _employee_query(
        search_term=search_term,
        designation=designation,
        include_admin_role=include_admin_role,
    )
    items = [_serialize(employee) for employee in db.employees.find(query).sort("created_at", DESCENDING)]
    return _hydrate_employees(db, items)


def add_admin_user(
    db: Database,
    username: str,
    password_hash: str,
    permissions: dict,
    *,
    role: str = "admin",
    doctor_id: str | None = None,
    active: bool = True,
) -> str | None:
    normalized = username.strip().lower()
    if not normalized:
        return None

    if db.admin_users.find_one({"username": normalized}):
        return None

    linked_doctor_id = _object_id(doctor_id) if doctor_id else None

    result = db.admin_users.insert_one(
        {
            "username": normalized,
            "password_hash": password_hash,
            "permissions": permissions,
            "role": role,
            "doctor_id": linked_doctor_id,
            "active": active,
            "created_at": datetime.utcnow(),
        }
    )
    return str(result.inserted_id)


def add_employee(db: Database, payload: dict) -> str:
    employee_id = str(payload.get("employee_id") or "").strip().upper()
    if not employee_id:
        counter = db.counters.find_one_and_update(
            {"_id": "employee_master_id"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        employee_id = f"EMP-{counter['seq']:05d}"
    document = {
        **payload,
        "employee_id": employee_id,
        "created_at": datetime.utcnow(),
    }
    result = db.employees.insert_one(document)
    return str(result.inserted_id)


def upsert_employee_for_user(db: Database, user_id: str, payload: dict) -> str | None:
    user_object_id = _object_id(user_id)
    if not user_object_id:
        return None

    existing = db.employees.find_one({"user_id": user_object_id})
    if existing:
        db.employees.update_one({"_id": existing["_id"]}, {"$set": payload})
        return str(existing["_id"])

    return add_employee(db, {**payload, "user_id": user_object_id})


def update_employee_active_by_user(db: Database, user_id: str, active: bool) -> bool:
    user_object_id = _object_id(user_id)
    if not user_object_id:
        return False
    result = db.employees.update_one({"user_id": user_object_id}, {"$set": {"is_active": active}})
    return result.matched_count > 0


def update_employee_name(db: Database, employee_id: str, first_name: str, last_name: str) -> bool:
    object_id = _object_id(employee_id)
    if not object_id:
        return False

    cleaned_first_name = first_name.strip()
    cleaned_last_name = last_name.strip()
    full_name = f"{cleaned_first_name} {cleaned_last_name}".strip()
    result = db.employees.update_one(
        {"_id": object_id},
        {
            "$set": {
                "first_name": cleaned_first_name,
                "last_name": cleaned_last_name,
                "full_name": full_name,
            }
        },
    )
    return result.matched_count > 0


def update_employee_profile(
    db: Database,
    employee_id: str,
    *,
    first_name: str,
    last_name: str,
    phone: str,
    email: str,
) -> bool:
    object_id = _object_id(employee_id)
    if not object_id:
        return False

    cleaned_first_name = first_name.strip()
    cleaned_last_name = last_name.strip()
    full_name = f"{cleaned_first_name} {cleaned_last_name}".strip()
    result = db.employees.update_one(
        {"_id": object_id},
        {
            "$set": {
                "first_name": cleaned_first_name,
                "last_name": cleaned_last_name,
                "full_name": full_name,
                "phone": phone.strip(),
                "email": email.strip(),
            }
        },
    )
    return result.matched_count > 0


def update_linked_doctor_profile(
    db: Database,
    doctor_id: str,
    *,
    doctor_phone: str,
    doctor_email: str,
    profile_summary: str,
    testimonial_summary: str,
) -> bool:
    object_id = _object_id(doctor_id)
    if not object_id:
        return False

    contact_parts: list[str] = []
    if doctor_phone.strip():
        contact_parts.append(f"Phone: {doctor_phone.strip()}")
    if doctor_email.strip():
        contact_parts.append(f"Email: {doctor_email.strip()}")
    contact_details = " | ".join(contact_parts)

    result = db.doctors.update_one(
        {"_id": object_id},
        {
            "$set": {
                "contact_details": contact_details,
                "bio": profile_summary.strip(),
                "testimonial_summary": testimonial_summary.strip(),
            }
        },
    )
    return result.matched_count > 0


def update_admin_status(db: Database, admin_id: str, active: bool) -> bool:
    object_id = _object_id(admin_id)
    if not object_id:
        return False

    result = db.admin_users.update_one({"_id": object_id}, {"$set": {"active": active}})
    return result.matched_count > 0


def add_review(db: Database, payload: dict) -> str:
    document = {**payload, "featured": True}
    result = db.reviews.insert_one(document)
    return str(result.inserted_id)


def update_review(db: Database, review_id: str, payload: dict) -> bool:
    object_id = _object_id(review_id)
    if not object_id:
        return False

    result = db.reviews.update_one({"_id": object_id}, {"$set": payload})
    return result.matched_count > 0


def update_appointment_status(db: Database, appointment_id: str, status_value: str) -> dict | None:
    object_id = _object_id(appointment_id)
    if not object_id:
        return None

    db.appointments.update_one({"_id": object_id}, {"$set": {"status": status_value}})
    appointment = db.appointments.find_one({"_id": object_id})
    return _serialize(appointment)


def update_appointment_doctor(db: Database, appointment_id: str, doctor_id: str | None) -> dict | None:
    object_id = _object_id(appointment_id)
    if not object_id:
        return None

    doctor_object_id = _object_id(doctor_id) if doctor_id else None
    db.appointments.update_one({"_id": object_id}, {"$set": {"doctor_id": doctor_object_id}})
    appointment = db.appointments.find_one({"_id": object_id})
    return _serialize(appointment)


def update_appointment_payment(
    db: Database,
    appointment_id: str,
    *,
    payment_status: str,
    payment_details: str,
) -> dict | None:
    object_id = _object_id(appointment_id)
    if not object_id:
        return None

    db.appointments.update_one(
        {"_id": object_id},
        {
            "$set": {
                "payment_status": payment_status.strip(),
                "payment_details": payment_details.strip(),
            }
        },
    )
    appointment = db.appointments.find_one({"_id": object_id})
    return _serialize(appointment)


def update_appointment_clinical_notes(
    db: Database,
    appointment_id: str,
    *,
    diagnosis_details: str,
    completion_notes: str,
    follow_up_duration: str,
    updated_by_doctor_id: str | None = None,
) -> dict | None:
    object_id = _object_id(appointment_id)
    if not object_id:
        return None

    payload: dict[str, object] = {
        "diagnosis_details": diagnosis_details.strip(),
        "completion_notes": completion_notes.strip(),
        "follow_up_duration": follow_up_duration.strip(),
        "completed_at": datetime.utcnow(),
        "status": "Completed",
    }
    if updated_by_doctor_id:
        doctor_object_id = _object_id(updated_by_doctor_id)
        if doctor_object_id:
            payload["completed_by_doctor_id"] = doctor_object_id

    db.appointments.update_one({"_id": object_id}, {"$set": payload})
    appointment = db.appointments.find_one({"_id": object_id})
    return _serialize(appointment)


def append_appointment_history(
    db: Database,
    appointment_id: str,
    *,
    action: str,
    actor_username: str,
    actor_role: str,
    changes: dict,
) -> bool:
    object_id = _object_id(appointment_id)
    if not object_id:
        return False
    _append_appointment_history(
        db,
        object_id,
        action=action,
        actor_username=actor_username.strip() or "system",
        actor_role=actor_role.strip() or "admin",
        changes=changes,
    )
    return True
