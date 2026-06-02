from __future__ import annotations

from pydantic import BaseModel, Field


class AppointmentCreate(BaseModel):
    patient_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    city: str = Field(min_length=2, max_length=80)
    appointment_date: str = Field(min_length=4, max_length=30)
    service_name: str = Field(min_length=2, max_length=150)
    notes: str = Field(default="", max_length=2000)
    doctor_id: str | None = None


class DoctorCreate(BaseModel):
    name: str
    title: str
    experience_years: int
    specialties: str
    bio: str
    testimonial_summary: str = ""
    photo_url: str = ""
    contact_details: str = ""
    document_url: str = ""
    active: bool = True


class AvailabilityCreate(BaseModel):
    doctor_id: str
    day_label: str
    time_range: str


class ReviewCreate(BaseModel):
    patient_name: str
    location: str
    quote: str
    rating: int = 5
    video_url: str = ""
