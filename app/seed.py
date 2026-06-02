from __future__ import annotations

from pymongo.database import Database
from pymongo import ReturnDocument


SERVICES = [
    (
        "Geriatric & Pediatric Physiotherapy",
        "Age-aware rehabilitation plans for seniors and children, with mobility, balance, and developmental support.",
    ),
    (
        "Manual & Electrotherapy",
        "Hands-on therapy and electrotherapy sessions designed to relieve pain and improve movement faster.",
    ),
    (
        "Arthritis & Joint Pain Care",
        "Supportive treatment for stiffness, swelling, and long-term joint pain with progressive rehab plans.",
    ),
    (
        "Post-Surgery & Fracture Rehab",
        "Structured recovery support after surgery, fractures, ligament repair, and replacement procedures.",
    ),
    (
        "Neuro Physiotherapy",
        "Focused therapy for stroke, paralysis, balance disorders, and neurological recovery at home.",
    ),
    (
        "Ortho Physiotherapy",
        "Recovery programs for spine, shoulder, knee, and sports-related orthopedic pain conditions.",
    ),
    (
        "Chiropractic",
        "Alignment-focused sessions to reduce back pain, improve posture, and restore comfortable movement.",
    ),
    (
        "Dry cupping theraphy",
        "Targeted cupping sessions to reduce muscle tightness, stiffness, and fatigue.",
    ),
    (
        "Dry Needling Therapy",
        "Trigger-point dry needling for chronic muscular pain, tension, and restricted range of motion.",
    ),
    (
        "Pediatric Physiotherapy",
        "Customized pediatric therapy for strength, coordination, posture, and developmental care.",
    ),
    (
        "Wet cupping theraphy",
        "Traditional wet cupping support for detox-focused care under controlled therapeutic practice.",
    ),
]


DOCTORS = [
    {
        "name": "Dr. Abdullah",
        "title": "Physiotherapy Specialist",
        "experience_years": 3,
        "specialties": "Orthopedic Rehab, Pain Management",
        "bio": "Focused on restoring mobility after injury, surgery, and long-standing joint pain conditions.",
        "photo_url": "https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?auto=format&fit=crop&w=900&q=80",
    },
    {
        "name": "Dr. Aditya",
        "title": "Physiotherapy Specialist",
        "experience_years": 3,
        "specialties": "Neuro Rehab, Home Care",
        "bio": "Works with stroke and mobility patients through guided home-based recovery programs.",
        "photo_url": "https://images.unsplash.com/photo-1537368910025-700350fe46c7?auto=format&fit=crop&w=900&q=80",
    },
    {
        "name": "Dr. Alka",
        "title": "Physiotherapy Specialist",
        "experience_years": 2,
        "specialties": "Women Wellness, Pediatric Support",
        "bio": "Delivers patient-friendly rehabilitation plans with calm communication and consistent follow-up.",
        "photo_url": "https://images.unsplash.com/photo-1594824476967-48c8b964273f?auto=format&fit=crop&w=900&q=80",
    },
]


REVIEWS = [
    {
        "patient_name": "Ritika S.",
        "location": "Patna",
        "quote": "The at-home rehab plan was clear, professional, and much easier for my family to manage.",
        "rating": 5,
        "video_url": "https://www.youtube.com/embed/dQw4w9WgXcQ",
    },
    {
        "patient_name": "Amit K.",
        "location": "Delhi",
        "quote": "Our therapist was punctual and explained every exercise in simple language. Recovery felt structured.",
        "rating": 5,
        "video_url": "",
    },
]


AVAILABILITY = [
    {"doctor_name": "Dr. Abdullah", "day_label": "Mon - Sat", "time_range": "9:00 AM - 1:00 PM"},
    {"doctor_name": "Dr. Aditya", "day_label": "Mon - Fri", "time_range": "2:00 PM - 7:00 PM"},
    {"doctor_name": "Dr. Alka", "day_label": "Tue - Sun", "time_range": "10:00 AM - 4:00 PM"},
]


DEFAULT_CITIES = [
    "Delhi",
    "Noida",
    "Gurgaon",
    "Ghaziabad",
    "Faridabad",
    "Patna",
]


def seed_database(db: Database) -> None:
    if db.services.count_documents({}) == 0:
        db.services.insert_many([{"title": title, "description": description} for title, description in SERVICES])

    if db.doctors.count_documents({}) == 0:
        doctor_docs = []
        for doctor_data in DOCTORS:
            counter = db.counters.find_one_and_update(
                {"_id": "doctor_employee_id"},
                {"$inc": {"seq": 1}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            doctor_docs.append({**doctor_data, "active": True, "employee_id": f"DOC-{counter['seq']:04d}"})
        db.doctors.insert_many(doctor_docs)
    else:
        doctors_without_employee_id = list(db.doctors.find({"employee_id": {"$exists": False}}))
        for doctor in doctors_without_employee_id:
            counter = db.counters.find_one_and_update(
                {"_id": "doctor_employee_id"},
                {"$inc": {"seq": 1}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            db.doctors.update_one(
                {"_id": doctor["_id"]},
                {"$set": {"employee_id": f"DOC-{counter['seq']:04d}"}},
            )

    if db.reviews.count_documents({}) == 0:
        db.reviews.insert_many([{**review_data, "featured": True} for review_data in REVIEWS])

    if db.cities.count_documents({}) == 0:
        db.cities.insert_many([{"name": city} for city in DEFAULT_CITIES])

    if db.availability_slots.count_documents({}) == 0:
        doctors = {doctor["name"]: doctor["_id"] for doctor in db.doctors.find({}, {"name": 1})}
        slot_documents = []
        for slot in AVAILABILITY:
            doctor_id = doctors.get(slot["doctor_name"])
            if doctor_id:
                slot_documents.append(
                    {
                        "doctor_id": doctor_id,
                        "day_label": slot["day_label"],
                        "time_range": slot["time_range"],
                    }
                )
        if slot_documents:
            db.availability_slots.insert_many(slot_documents)
