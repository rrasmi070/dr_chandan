from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import get_db
from app.repository import (
    create_appointment as create_appointment_record,
    list_cities,
    list_doctors,
    list_reviews,
    list_services,
)
from app.schemas import AppointmentCreate


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


def _sanitize_public_doctors(doctors: list[dict]) -> list[dict]:
    sanitized = []
    for doctor in doctors:
        public_doctor = dict(doctor)
        public_doctor.pop("contact_details", None)
        sanitized.append(public_doctor)
    return sanitized


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    db = get_db()
    services = list_services(db)
    doctors = _sanitize_public_doctors(list_doctors(db, active_only=True))
    reviews = list_reviews(db, featured_only=True)
    cities = list_cities(db)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "services": services,
            "doctors": doctors,
            "reviews": reviews,
            "cities": cities,
        },
    )


@router.get("/about-us", response_class=HTMLResponse)
def about_us(request: Request) -> HTMLResponse:
    db = get_db()
    return templates.TemplateResponse(
        request,
        "about_us.html",
        {
            "cities": list_cities(db),
            "doctors": _sanitize_public_doctors(list_doctors(db, active_only=True)),
        },
    )


@router.get("/contact-us", response_class=HTMLResponse)
def contact_us(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "contact_us.html",
        {},
    )


@router.post("/appointments")
def create_appointment(
    request: Request,
    patient_name: str = Form(...),
    phone: str = Form(...),
    city: str = Form(...),
    appointment_date: str = Form(...),
    service_name: str = Form(...),
    notes: str = Form(""),
    doctor_id: str = Form(""),
) -> RedirectResponse:
    db = get_db()
    payload = AppointmentCreate(
        patient_name=patient_name,
        phone=phone,
        city=city,
        appointment_date=appointment_date,
        service_name=service_name,
        notes=notes,
        doctor_id=doctor_id.strip() or None,
    )
    create_appointment_record(db, payload.model_dump())
    return RedirectResponse(url="/?appointment=success", status_code=status.HTTP_303_SEE_OTHER)
