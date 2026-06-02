from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook

from app.auth import (
    get_linked_doctor_id,
    get_user_role,
    has_permission,
    is_admin_user,
    is_doctor_user,
    is_reception_user,
    is_staf_user,
    is_logged_in,
    normalize_role,
)
from app.config import DOCTOR_DOCUMENTS_DIR, DOCTOR_UPLOADS_DIR
from app.config import EMPLOYEE_DOCUMENTS_DIR
from app.database import get_db
from app.repository import (
    append_appointment_history,
    add_admin_user as add_admin_user_record,
    add_availability as add_availability_record,
    add_city as add_city_record,
    add_doctor as add_doctor_record,
    add_review as add_review_record,
    add_service as add_service_record,
    get_employee_detail,
    get_appointment,
    get_admin_for_login,
    list_employee_designations,
    list_employees_page,
    list_employees_for_export,
    list_admin_users_page,
    list_appointments_for_export,
    list_appointments_page,
    list_cities,
    list_doctors,
    list_doctors_page,
    list_reviews_page,
    list_services,
    update_admin_status as update_admin_status_record,
    update_employee_profile,
    update_linked_doctor_profile,
    update_appointment_clinical_notes,
    update_appointment_doctor,
    update_appointment_payment,
    update_city as update_city_record,
    update_doctor,
    update_doctor_status as update_doctor_status_record,
    update_review as update_review_record,
    update_service as update_service_record,
    update_appointment_status as update_appointment_status_record,
    update_employee_active_by_user,
    upsert_employee_for_user,
)
from app.schemas import AvailabilityCreate, DoctorCreate, ReviewCreate
from app.security import hash_password, verify_password
from app.services.whatsapp import send_status_update


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/admin", tags=["admin"])

DEFAULT_PAGE_SIZE = 8
DEFAULT_USER_PASSWORD = "Password@123"


def _is_frontdesk_role(request: Request) -> bool:
    return is_reception_user(request) or is_staf_user(request)


def _role_label(role: str) -> str:
    return {
        "admin": "Admin",
        "doctor": "Doctor",
        "reception": "Reception",
        "staf": "Staf",
    }.get(role, "Admin")


def _sanitize_history_for_role(history: list[dict], role: str) -> list[dict]:
    if role != "doctor":
        return history

    sanitized: list[dict] = []
    for entry in history:
        item = dict(entry)
        changes = dict(item.get("changes") or {})
        changes.pop("payment_status", None)
        changes.pop("payment_details", None)
        item["changes"] = changes
        sanitized.append(item)
    return sanitized


def _normalize_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on", "active"}


async def _save_photo(upload: UploadFile | None) -> str:
    if not upload or not upload.filename:
        return ""
    extension = Path(upload.filename).suffix.lower() or ".jpg"
    filename = f"doctor-{uuid4().hex}{extension}"
    target = DOCTOR_UPLOADS_DIR / filename
    content = await upload.read()
    target.write_bytes(content)
    return f"/uploads/doctors/{filename}"


async def _save_doctor_document(upload: UploadFile | None) -> str:
    if not upload or not upload.filename:
        return ""

    extension = Path(upload.filename).suffix.lower() or ".pdf"
    if extension != ".pdf":
        raise ValueError("Only PDF files are allowed for doctor documents")

    filename = f"doctor-doc-{uuid4().hex}.pdf"
    target = DOCTOR_DOCUMENTS_DIR / filename
    content = await upload.read()
    target.write_bytes(content)
    return f"/uploads/doctor-documents/{filename}"


async def _save_employee_document(upload: UploadFile | None) -> str:
    if not upload or not upload.filename:
        return ""

    extension = Path(upload.filename).suffix.lower() or ".pdf"
    filename = f"employee-doc-{uuid4().hex}{extension}"
    target = EMPLOYEE_DOCUMENTS_DIR / filename
    content = await upload.read()
    target.write_bytes(content)
    return f"/uploads/employee-documents/{filename}"


def _admin_required(request: Request) -> RedirectResponse | None:
    if not is_logged_in(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    return None


def _current_admin_page(request: Request) -> str:
    return request.url.path


def _message_redirect(path: str, message: str, *, query_params: dict[str, str] | None = None) -> RedirectResponse:
    parsed = urlparse(path)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["message"] = message.replace(" ", "+")
    if query_params:
        params.update({key: value for key, value in query_params.items() if value != ""})
    rebuilt = parsed._replace(query=urlencode(params))
    return RedirectResponse(url=urlunparse(rebuilt), status_code=status.HTTP_303_SEE_OTHER)


def _parse_page(request: Request, key: str = "page") -> int:
    raw_value = request.query_params.get(key, "1")
    try:
        page = int(raw_value)
    except ValueError:
        page = 1
    return max(1, page)


def _page_link(request: Request, page: int, *, key: str = "page") -> str:
    params = dict(request.query_params)
    params[key] = str(max(1, page))
    query = urlencode(params)
    return f"{request.url.path}?{query}" if query else request.url.path


def _admin_shell_context(request: Request) -> dict:
    role = get_user_role(request)
    return {
        "current_admin_username": request.session.get("admin_username", ""),
        "current_role": role,
        "current_role_label": _role_label(role),
        "can_add_doctor": has_permission(request, "can_add_doctor"),
        "can_manage_admins": has_permission(request, "can_manage_admins"),
        "status_message": request.query_params.get("message", "").replace("+", " "),
        "current_path": _current_admin_page(request),
    }


def _appointments_scope(request: Request) -> tuple[str | None, str]:
    if is_doctor_user(request):
        return get_linked_doctor_id(request) or None, "doctor"
    return None, "admin"


def _appointment_filters(request: Request) -> dict[str, str]:
    return {
        "start_date": request.query_params.get("start_date", ""),
        "end_date": request.query_params.get("end_date", ""),
        "search": request.query_params.get("search", "").strip(),
    }


def _appointment_list_params(request: Request) -> dict[str, str]:
    return {
        "search": request.query_params.get("search", "").strip(),
        "start_date": request.query_params.get("start_date", ""),
        "end_date": request.query_params.get("end_date", ""),
        "page": request.query_params.get("page", "1"),
    }


def _employee_filters(request: Request) -> dict[str, str]:
    return {
        "search": request.query_params.get("search", "").strip(),
        "designation": request.query_params.get("designation", "").strip(),
    }


def _extract_doctor_contact(contact_details: str) -> tuple[str, str]:
    if not contact_details:
        return "", ""

    phone = ""
    email = ""
    for part in [segment.strip() for segment in contact_details.split("|")]:
        lowered = part.lower()
        if lowered.startswith("phone:"):
            phone = part.split(":", 1)[1].strip()
        elif lowered.startswith("email:"):
            email = part.split(":", 1)[1].strip()
    return phone, email


def _appointment_list_url(params: dict[str, str]) -> str:
    query = urlencode({k: v for k, v in params.items() if v})
    return f"/admin/appointments?{query}" if query else "/admin/appointments"


def _appointment_detail_url(appointment_id: str, params: dict[str, str]) -> str:
    query = urlencode({k: v for k, v in params.items() if v})
    return f"/admin/appointments/{appointment_id}?{query}" if query else f"/admin/appointments/{appointment_id}"


async def _apply_appointment_update(
    request: Request,
    appointment_id: str,
    *,
    status_value: str,
    diagnosis_details: str,
    completion_notes: str,
    follow_up_duration: str,
    payment_status: str,
    payment_details: str,
    doctor_id: str,
    redirect_to_detail: bool,
) -> RedirectResponse:
    db = get_db()
    current_appointment = get_appointment(db, appointment_id)
    if not current_appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    list_params = _appointment_list_params(request)

    if is_doctor_user(request):
        linked_doctor_id = get_linked_doctor_id(request)
        if not linked_doctor_id or current_appointment.get("doctor_id") != linked_doctor_id:
            return _message_redirect("/admin/appointments", "You can only update your assigned appointments", query_params=list_params)
        chosen_doctor_id = linked_doctor_id
    elif _is_frontdesk_role(request):
        chosen_doctor_id = doctor_id.strip() if doctor_id else ""
    else:
        chosen_doctor_id = doctor_id.strip() if doctor_id else ""

    effective_doctor_id = chosen_doctor_id or current_appointment.get("doctor_id") or ""
    if status_value in {"Confirmed", "In Progress", "Completed"} and not effective_doctor_id:
        message = "Assign a doctor before moving appointment to confirmed, in-progress, or completed"
        if redirect_to_detail:
            return _message_redirect(_appointment_detail_url(appointment_id, list_params), message)
        return _message_redirect("/admin/appointments", message, query_params=list_params)

    if not is_doctor_user(request) and chosen_doctor_id and chosen_doctor_id != current_appointment.get("doctor_id"):
        updated_assignment = update_appointment_doctor(db, appointment_id, chosen_doctor_id)
        if not updated_assignment:
            if redirect_to_detail:
                return _message_redirect(_appointment_detail_url(appointment_id, list_params), "Unable to assign doctor")
            return _message_redirect("/admin/appointments", "Unable to assign doctor", query_params=list_params)

    if is_doctor_user(request) and status_value not in {"In Progress", "Completed"}:
        status_value = current_appointment.get("status") or "Pending"

    if _is_frontdesk_role(request) and status_value == "Completed":
        return _message_redirect(
            _appointment_detail_url(appointment_id, list_params) if redirect_to_detail else "/admin/appointments",
            "Reception and staf cannot mark appointment as completed",
            query_params=None if redirect_to_detail else list_params,
        )

    if _is_frontdesk_role(request):
        normalized_payment_status = payment_status.strip() or current_appointment.get("payment_status", "Pending")
        payment_details_value = payment_details.strip()
        if normalized_payment_status not in {"Pending", "Confirmed", "Cancelled"}:
            normalized_payment_status = "Pending"
        payment_update = update_appointment_payment(
            db,
            appointment_id,
            payment_status=normalized_payment_status,
            payment_details=payment_details_value,
        )
        if not payment_update:
            return _message_redirect("/admin/appointments", "Unable to update payment details", query_params=list_params)

    if status_value == "Completed":
        if not diagnosis_details.strip() or not follow_up_duration.strip():
            message = "Diagnosis details and follow-up duration are required to complete an appointment"
            if redirect_to_detail:
                return _message_redirect(_appointment_detail_url(appointment_id, list_params), message)
            return _message_redirect("/admin/appointments", message, query_params=list_params)
        appointment = update_appointment_clinical_notes(
            db,
            appointment_id,
            diagnosis_details=diagnosis_details,
            completion_notes=completion_notes,
            follow_up_duration=follow_up_duration,
            updated_by_doctor_id=get_linked_doctor_id(request) or effective_doctor_id or None,
        )
    else:
        appointment = update_appointment_status_record(db, appointment_id, status_value)

    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    history_changes: dict[str, str] = {
        "status": status_value,
    }
    if chosen_doctor_id and chosen_doctor_id != (current_appointment.get("doctor_id") or ""):
        history_changes["doctor_id"] = chosen_doctor_id
    if diagnosis_details.strip():
        history_changes["diagnosis_details"] = diagnosis_details.strip()
    if completion_notes.strip():
        history_changes["completion_notes"] = completion_notes.strip()
    if follow_up_duration.strip():
        history_changes["follow_up_duration"] = follow_up_duration.strip()
    if _is_frontdesk_role(request):
        history_changes["payment_status"] = payment_status.strip() or current_appointment.get("payment_status", "Pending")
        if payment_details.strip():
            history_changes["payment_details"] = payment_details.strip()

    append_appointment_history(
        db,
        appointment_id,
        action="appointment_update",
        actor_username=request.session.get("admin_username", "system"),
        actor_role=get_user_role(request),
        changes=history_changes,
    )

    sent, message = await send_status_update(appointment["phone"], appointment["patient_name"], status_value)
    success_message = "Appointment updated and WhatsApp sent" if sent else "Appointment updated"
    if message and not sent:
        success_message = f"Appointment updated. {message}"

    if redirect_to_detail:
        return _message_redirect(_appointment_detail_url(appointment_id, list_params), success_message)
    return _message_redirect("/admin/appointments", success_message, query_params=list_params)


def _build_appointments_workbook(appointments: list[dict]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Appointments"
    sheet.append([
        "Patient Name",
        "Phone",
        "City",
        "Appointment Date",
        "Service",
        "Doctor",
        "Status",
        "Diagnosis Details",
        "Completion Notes",
        "Follow Up Duration",
        "Created At",
    ])

    for appointment in appointments:
        sheet.append([
            appointment.get("patient_name", ""),
            appointment.get("phone", ""),
            appointment.get("city", ""),
            appointment.get("appointment_date", ""),
            appointment.get("service_name", ""),
            appointment.get("doctor", {}).get("name", "Not assigned") if appointment.get("doctor") else "Not assigned",
            appointment.get("status", ""),
            appointment.get("diagnosis_details", ""),
            appointment.get("completion_notes", ""),
            appointment.get("follow_up_duration", ""),
            str(appointment.get("created_at", "")),
        ])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def _build_employees_workbook(employees: list[dict]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Employees"
    sheet.append([
        "Employee ID",
        "Full Name",
        "Role",
        "Designation",
        "Phone",
        "Email",
        "Doctor Phone",
        "Doctor Email",
        "Username",
        "Active",
        "DOB",
        "Joining Date",
        "Linked Doctor",
        "Doctor Profile Summary",
        "Doctor Testimonial Summary",
    ])

    for employee in employees:
        role_value = employee.get("user_role") or ((employee.get("user") or {}).get("role") or "")
        linked_doctor = employee.get("linked_doctor") or {}
        doctor_phone, doctor_email = _extract_doctor_contact(linked_doctor.get("contact_details", ""))
        sheet.append([
            employee.get("employee_id", ""),
            employee.get("full_name", ""),
            role_value,
            employee.get("designation", ""),
            employee.get("phone", ""),
            employee.get("email", ""),
            doctor_phone,
            doctor_email,
            employee.get("username", "") or ((employee.get("user") or {}).get("username") or ""),
            "Yes" if employee.get("is_active") else "No",
            employee.get("dob", ""),
            employee.get("joining_date", ""),
            linked_doctor.get("name", ""),
            linked_doctor.get("bio", ""),
            linked_doctor.get("testimonial_summary", ""),
        ])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def _permission_required(request: Request, key: str) -> RedirectResponse | None:
    if not has_permission(request, key):
        return RedirectResponse(url=f"/admin?message=Permission+denied+for+{key}", status_code=status.HTTP_303_SEE_OTHER)
    return None


def _admin_role_required(request: Request) -> RedirectResponse | None:
    if not is_admin_user(request):
        return RedirectResponse(url="/admin/appointments?message=Permission+denied+for+this+role", status_code=status.HTTP_303_SEE_OTHER)
    return None


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "admin_login.html", {"error": "", "selected_role": "admin"})


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, identifier: str = Form(...), password: str = Form(...), role: str = Form("admin")):
    db = get_db()
    selected_role = normalize_role(role)
    admin_user = get_admin_for_login(db, identifier, selected_role)
    if not admin_user or not verify_password(password, admin_user.get("password_hash", "")):
        return templates.TemplateResponse(
            request,
            "admin_login.html",
            {"error": "Invalid credentials.", "selected_role": selected_role},
            status_code=400,
        )

    user_role = normalize_role(admin_user.get("role", "admin"))
    if selected_role != user_role:
        return templates.TemplateResponse(
            request,
            "admin_login.html",
            {"error": f"This account is not allowed for {selected_role.title()} login.", "selected_role": selected_role},
            status_code=400,
        )

    request.session["is_admin"] = True
    request.session["admin_user_id"] = admin_user["id"]
    request.session["admin_username"] = admin_user["username"]
    request.session["permissions"] = admin_user.get("permissions", {})
    request.session["role"] = user_role
    request.session["doctor_id"] = admin_user.get("doctor_id", "")

    target_path = "/admin" if user_role == "admin" else "/admin/appointments"
    return RedirectResponse(url=target_path, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    if not is_admin_user(request):
        return RedirectResponse(url="/admin/appointments", status_code=status.HTTP_303_SEE_OTHER)

    db = get_db()
    doctors_page = list_doctors_page(db, page=_parse_page(request, "doctors_page"), per_page=DEFAULT_PAGE_SIZE)
    return templates.TemplateResponse(
        request,
        "admin_dashboard.html",
        {
            **_admin_shell_context(request),
            "doctors_page": doctors_page,
            "services": list_services(db),
            "cities": list_cities(db),
            "doctors": list_doctors(db),
            "doctor_page_links": {
                "prev": _page_link(request, doctors_page["prev_page"], key="doctors_page"),
                "next": _page_link(request, doctors_page["next_page"], key="doctors_page"),
            },
        },
    )


@router.get("/appointments", response_class=HTMLResponse)
def appointments_page(request: Request) -> HTMLResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect

    db = get_db()
    filters = _appointment_filters(request)
    scoped_doctor_id, access_scope = _appointments_scope(request)
    appointments_page_data = list_appointments_page(
        db,
        page=_parse_page(request),
        per_page=DEFAULT_PAGE_SIZE,
        start_date=filters["start_date"] or None,
        end_date=filters["end_date"] or None,
        doctor_id=scoped_doctor_id,
        search_term=filters["search"] or None,
    )
    return templates.TemplateResponse(
        request,
        "admin_appointments.html",
        {
            **_admin_shell_context(request),
            "appointments_page": appointments_page_data,
            "appointment_filters": filters,
            "appointments_page_links": {
                "prev": _page_link(request, appointments_page_data["prev_page"]),
                "next": _page_link(request, appointments_page_data["next_page"]),
            },
            "access_scope": access_scope,
        },
    )


@router.get("/appointments/{appointment_id}", response_class=HTMLResponse)
def appointment_detail_page(appointment_id: str, request: Request) -> HTMLResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect

    db = get_db()
    appointment = get_appointment(db, appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if is_doctor_user(request):
        linked_doctor_id = get_linked_doctor_id(request)
        if not linked_doctor_id or appointment.get("doctor_id") != linked_doctor_id:
            return _message_redirect("/admin/appointments", "You can only view your assigned appointments")

    current_role = get_user_role(request)
    can_manage_payment = _is_frontdesk_role(request) or is_admin_user(request)
    can_assign_doctor = _is_frontdesk_role(request) or is_admin_user(request)
    can_edit_clinical = is_doctor_user(request) or is_admin_user(request)
    appointment_history = _sanitize_history_for_role(list(reversed(appointment.get("history") or [])), current_role)

    list_params = _appointment_list_params(request)
    return templates.TemplateResponse(
        request,
        "admin_appointment_detail.html",
        {
            **_admin_shell_context(request),
            "appointment": appointment,
            "doctors": list_doctors(db, active_only=True),
            "can_manage_payment": can_manage_payment,
            "can_assign_doctor": can_assign_doctor,
            "can_edit_clinical": can_edit_clinical,
            "appointment_history": appointment_history,
            "list_url": _appointment_list_url(list_params),
            "query_suffix": urlencode({k: v for k, v in list_params.items() if v}),
        },
    )


@router.get("/appointments/export")
def export_appointments(request: Request) -> StreamingResponse:
    redirect = _admin_required(request)
    if redirect:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")

    db = get_db()
    filters = _appointment_filters(request)
    scoped_doctor_id, _ = _appointments_scope(request)
    appointments = list_appointments_for_export(
        db,
        start_date=filters["start_date"] or None,
        end_date=filters["end_date"] or None,
        doctor_id=scoped_doctor_id,
        search_term=filters["search"] or None,
    )
    output = _build_appointments_workbook(appointments)
    headers = {"Content-Disposition": 'attachment; filename="appointments.xlsx"'}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/reviews", response_class=HTMLResponse)
def reviews_page(request: Request) -> HTMLResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    if not is_admin_user(request):
        return RedirectResponse(url="/admin/appointments", status_code=status.HTTP_303_SEE_OTHER)

    db = get_db()
    reviews_page_data = list_reviews_page(db, page=_parse_page(request), per_page=DEFAULT_PAGE_SIZE)
    return templates.TemplateResponse(
        request,
        "admin_reviews.html",
        {
            **_admin_shell_context(request),
            "reviews_page": reviews_page_data,
            "review_page_links": {
                "prev": _page_link(request, reviews_page_data["prev_page"]),
                "next": _page_link(request, reviews_page_data["next_page"]),
            },
        },
    )


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request) -> HTMLResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    if not is_admin_user(request):
        return RedirectResponse(url="/admin/appointments", status_code=status.HTTP_303_SEE_OTHER)

    db = get_db()
    admins_page_data = list_admin_users_page(
        db,
        page=_parse_page(request),
        per_page=DEFAULT_PAGE_SIZE,
        include_admin_role=False,
    )
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            **_admin_shell_context(request),
            "admins_page": admins_page_data,
            "doctors": list_doctors(db),
            "user_page_links": {
                "prev": _page_link(request, admins_page_data["prev_page"]),
                "next": _page_link(request, admins_page_data["next_page"]),
            },
        },
    )


@router.get("/employees", response_class=HTMLResponse)
def employees_page(request: Request) -> HTMLResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    if not is_admin_user(request):
        return RedirectResponse(url="/admin/appointments", status_code=status.HTTP_303_SEE_OTHER)

    db = get_db()
    filters = _employee_filters(request)
    employees_page_data = list_employees_page(
        db,
        page=_parse_page(request),
        per_page=DEFAULT_PAGE_SIZE,
        search_term=filters["search"] or None,
        designation=filters["designation"] or None,
        include_admin_role=False,
    )
    return templates.TemplateResponse(
        request,
        "admin_employees.html",
        {
            **_admin_shell_context(request),
            "employees_page": employees_page_data,
            "employee_filters": filters,
            "designation_options": list_employee_designations(db, include_admin_role=False),
            "employees_page_links": {
                "prev": _page_link(request, employees_page_data["prev_page"]),
                "next": _page_link(request, employees_page_data["next_page"]),
            },
        },
    )


@router.get("/employees/export")
def export_employees(request: Request) -> StreamingResponse:
    redirect = _admin_required(request)
    if redirect:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    if not is_admin_user(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    db = get_db()
    filters = _employee_filters(request)
    employees = list_employees_for_export(
        db,
        search_term=filters["search"] or None,
        designation=filters["designation"] or None,
        include_admin_role=False,
    )
    output = _build_employees_workbook(employees)
    headers = {"Content-Disposition": 'attachment; filename="employees.xlsx"'}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/employees/{employee_id}", response_class=HTMLResponse)
def employee_detail_page(employee_id: str, request: Request) -> HTMLResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    if not is_admin_user(request):
        return RedirectResponse(url="/admin/appointments", status_code=status.HTTP_303_SEE_OTHER)

    db = get_db()
    employee = get_employee_detail(db, employee_id, include_admin_role=False)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    linked_doctor = employee.get("linked_doctor") or {}
    doctor_phone, doctor_email = _extract_doctor_contact(linked_doctor.get("contact_details", ""))

    page = max(1, _parse_page(request))
    return templates.TemplateResponse(
        request,
        "admin_employee_detail.html",
        {
            **_admin_shell_context(request),
            "employee": employee,
            "doctor_phone": doctor_phone,
            "doctor_email": doctor_email,
            "employees_list_url": f"/admin/employees?page={page}",
        },
    )


@router.get("/employees/{employee_id}/edit", response_class=HTMLResponse)
def employee_edit_page(employee_id: str, request: Request) -> HTMLResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    if not is_admin_user(request):
        return RedirectResponse(url="/admin/appointments", status_code=status.HTTP_303_SEE_OTHER)

    db = get_db()
    employee = get_employee_detail(db, employee_id, include_admin_role=False)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    linked_doctor = employee.get("linked_doctor") or {}
    doctor_phone, doctor_email = _extract_doctor_contact(linked_doctor.get("contact_details", ""))

    return templates.TemplateResponse(
        request,
        "admin_employee_edit.html",
        {
            **_admin_shell_context(request),
            "employee": employee,
            "doctor_phone": doctor_phone,
            "doctor_email": doctor_email,
            "doctor_profile_summary": linked_doctor.get("bio", ""),
            "doctor_testimonial_summary": linked_doctor.get("testimonial_summary", ""),
            "page": _parse_page(request),
            "search": request.query_params.get("search", "").strip(),
            "designation": request.query_params.get("designation", "").strip(),
        },
    )


@router.post("/employees/{employee_id}/edit")
def employee_edit_profile(
    employee_id: str,
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    doctor_phone: str = Form(""),
    doctor_email: str = Form(""),
    doctor_profile_summary: str = Form(""),
    doctor_testimonial_summary: str = Form(""),
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    if not is_admin_user(request):
        return RedirectResponse(url="/admin/appointments", status_code=status.HTTP_303_SEE_OTHER)

    cleaned_first_name = first_name.strip()
    cleaned_last_name = last_name.strip()
    if not cleaned_first_name or not cleaned_last_name:
        return _message_redirect(f"/admin/employees/{employee_id}/edit", "First name and last name are required")

    db = get_db()
    if not update_employee_profile(
        db,
        employee_id,
        first_name=cleaned_first_name,
        last_name=cleaned_last_name,
        phone=phone,
        email=email,
    ):
        return _message_redirect("/admin/employees", "Employee not found")

    employee = get_employee_detail(db, employee_id, include_admin_role=False)
    if employee and employee.get("linked_doctor"):
        linked_doctor_id = employee["linked_doctor"].get("id", "")
        if linked_doctor_id:
            update_linked_doctor_profile(
                db,
                linked_doctor_id,
                doctor_phone=doctor_phone,
                doctor_email=doctor_email,
                profile_summary=doctor_profile_summary,
                testimonial_summary=doctor_testimonial_summary,
            )

    page = request.query_params.get("page", "1").strip() or "1"
    search = request.query_params.get("search", "").strip()
    designation = request.query_params.get("designation", "").strip()
    query = urlencode({"page": page, "search": search, "designation": designation})
    return RedirectResponse(
        url=f"/admin/employees?{query}&message=Employee+details+updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users")
async def add_admin_user(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    dob: str = Form(...),
    joining_date: str = Form(...),
    designation: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    doctor_experience_years: int = Form(1),
    doctor_specialties: str = Form(""),
    doctor_profile_summary: str = Form(""),
    doctor_testimonial_summary: str = Form(""),
    doctor_photo_url: str = Form(""),
    doctor_photo_file: UploadFile | None = None,
    document_url: str = Form(""),
    employee_document_file: UploadFile | None = None,
    role: str = Form("admin"),
    can_add_doctor: str = Form("false"),
    can_manage_admins: str = Form("false"),
    active: str = Form("true"),
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    permission_redirect = _permission_required(request, "can_manage_admins")
    if permission_redirect:
        return permission_redirect

    db = get_db()
    normalized_role = normalize_role(role)

    if not first_name.strip() or not last_name.strip():
        return _message_redirect("/admin/users", "First name and last name are required")
    if not dob.strip() or not joining_date.strip():
        return _message_redirect("/admin/users", "DOB and joining date are required")

    username_base = f"{first_name.strip()} {last_name.strip()}"
    username_slug = re.sub(r"[^a-z0-9]+", ".", username_base.lower()).strip(".")
    if not username_slug:
        username_slug = "user"

    normalized_username = f"{username_slug}.{normalized_role}"
    suffix = 1
    while db.admin_users.find_one({"username": normalized_username}):
        suffix += 1
        normalized_username = f"{username_slug}.{normalized_role}{suffix}"

    permissions = {
        "can_add_doctor": normalized_role == "admin" and _normalize_bool(can_add_doctor),
        "can_manage_admins": normalized_role == "admin" and _normalize_bool(can_manage_admins),
    }
    is_active = _normalize_bool(active)
    uploaded_employee_document = await _save_employee_document(employee_document_file)
    created = add_admin_user_record(
        db,
        normalized_username,
        hash_password(DEFAULT_USER_PASSWORD),
        permissions,
        role=normalized_role,
        doctor_id=None,
        active=is_active,
    )
    if not created:
        return _message_redirect("/admin/users", "Admin username already exists")

    linked_doctor = None
    linked_doctor_id = ""
    if normalized_role == "doctor":
        auto_doctor_name = f"Dr. {first_name.strip()} {last_name.strip()}".replace("Dr. Dr.", "Dr.").strip()
        auto_title = designation.strip() or "Physiotherapy Specialist"
        experience_years_value = doctor_experience_years if doctor_experience_years > 0 else 1
        specialties_value = doctor_specialties.strip() or "General Physiotherapy"
        profile_summary_value = doctor_profile_summary.strip() or f"{auto_doctor_name} profile created via user onboarding."
        testimonial_summary_value = doctor_testimonial_summary.strip()
        uploaded_doctor_photo = await _save_photo(doctor_photo_file)
        doctor_photo_value = uploaded_doctor_photo or doctor_photo_url.strip()
        auto_contact = ""
        if phone.strip() or email.strip():
            contact_parts: list[str] = []
            if phone.strip():
                contact_parts.append(f"Phone: {phone.strip()}")
            if email.strip():
                contact_parts.append(f"Email: {email.strip()}")
            auto_contact = " | ".join(contact_parts)

        try:
            doctor_payload = DoctorCreate(
                name=auto_doctor_name,
                title=auto_title,
                experience_years=experience_years_value,
                specialties=specialties_value,
                bio=profile_summary_value,
                testimonial_summary=testimonial_summary_value,
                photo_url=doctor_photo_value,
                contact_details=auto_contact,
                document_url=uploaded_employee_document or document_url.strip(),
                active=is_active,
            )
            linked_doctor_id = add_doctor_record(db, doctor_payload.model_dump())
            if ObjectId.is_valid(created) and ObjectId.is_valid(linked_doctor_id):
                db.admin_users.update_one(
                    {"_id": ObjectId(created)},
                    {"$set": {"doctor_id": ObjectId(linked_doctor_id)}},
                )
                linked_doctor = db.doctors.find_one({"_id": ObjectId(linked_doctor_id)})
        except Exception:
            if ObjectId.is_valid(created):
                db.admin_users.delete_one({"_id": ObjectId(created)})
            return _message_redirect("/admin/users", "Unable to auto-create doctor profile")

    employee_payload = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "full_name": f"{first_name.strip()} {last_name.strip()}".strip(),
        "dob": dob.strip(),
        "joining_date": joining_date.strip(),
        "designation": designation.strip(),
        "user_role": normalized_role,
        "is_active": is_active,
        "username": normalized_username,
        "phone": phone.strip(),
        "email": email.strip(),
        "address": address.strip(),
        "documents": [value for value in [uploaded_employee_document, document_url.strip()] if value],
        "linked_doctor_id": linked_doctor_id if normalized_role == "doctor" else "",
    }

    if linked_doctor and linked_doctor.get("employee_id"):
        employee_payload["employee_id"] = linked_doctor.get("employee_id")

    try:
        employee_id = upsert_employee_for_user(db, created, employee_payload)
    except Exception:
        if ObjectId.is_valid(created):
            db.admin_users.delete_one({"_id": ObjectId(created)})
        return _message_redirect("/admin/users", "Unable to create employee profile")
    if not employee_id:
        if ObjectId.is_valid(created):
            db.admin_users.delete_one({"_id": ObjectId(created)})
        return _message_redirect("/admin/users", "Unable to create employee profile")

    if normalized_role == "doctor" and linked_doctor and linked_doctor.get("employee_id"):
        return _message_redirect(
            "/admin/users",
            f"Doctor user created. Employee ID: {linked_doctor.get('employee_id')}. Default password: {DEFAULT_USER_PASSWORD}",
        )
    return _message_redirect("/admin/users", f"User created. Default password: {DEFAULT_USER_PASSWORD}")


@router.post("/users/{admin_id}/status")
def update_admin_status(admin_id: str, request: Request, active: str = Form(...)) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    permission_redirect = _permission_required(request, "can_manage_admins")
    if permission_redirect:
        return permission_redirect

    db = get_db()
    if not update_admin_status_record(db, admin_id, _normalize_bool(active)):
        return _message_redirect("/admin/users", "Admin user not found")
    update_employee_active_by_user(db, admin_id, _normalize_bool(active))
    return _message_redirect("/admin/users", "Admin status updated")


@router.post("/doctors")
async def add_doctor(
    request: Request,
    name: str = Form(...),
    title: str = Form(...),
    experience_years: int = Form(...),
    specialties: str = Form(...),
    bio: str = Form(...),
    testimonial_summary: str = Form(""),
    contact_details: str = Form(""),
    photo_url: str = Form(""),
    document_url: str = Form(""),
    active: str = Form("true"),
    photo_file: UploadFile | None = None,
    document_file: UploadFile | None = None,
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    permission_redirect = _permission_required(request, "can_add_doctor")
    if permission_redirect:
        return permission_redirect

    try:
        uploaded_document_path = await _save_doctor_document(document_file)
    except ValueError:
        return RedirectResponse(url="/admin?message=Only+PDF+documents+are+allowed", status_code=status.HTTP_303_SEE_OTHER)

    uploaded_photo_path = await _save_photo(photo_file)
    payload = DoctorCreate(
        name=name,
        title=title,
        experience_years=experience_years,
        specialties=specialties,
        bio=bio,
        testimonial_summary=testimonial_summary.strip(),
        contact_details=contact_details.strip(),
        photo_url=uploaded_photo_path or photo_url,
        document_url=uploaded_document_path or document_url.strip(),
        active=_normalize_bool(active),
    )
    db = get_db()
    add_doctor_record(db, payload.model_dump())
    return RedirectResponse(url="/admin?message=Doctor+saved+with+employee+ID", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/doctors/{doctor_id}/edit")
async def edit_doctor(
    doctor_id: str,
    request: Request,
    name: str = Form(...),
    title: str = Form(...),
    experience_years: int = Form(...),
    specialties: str = Form(...),
    bio: str = Form(...),
    testimonial_summary: str = Form(""),
    contact_details: str = Form(""),
    photo_url: str = Form(""),
    document_url: str = Form(""),
    active: str = Form("true"),
    photo_file: UploadFile | None = None,
    document_file: UploadFile | None = None,
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    permission_redirect = _permission_required(request, "can_add_doctor")
    if permission_redirect:
        return permission_redirect

    try:
        uploaded_document_path = await _save_doctor_document(document_file)
    except ValueError:
        return RedirectResponse(url="/admin?message=Only+PDF+documents+are+allowed", status_code=status.HTTP_303_SEE_OTHER)

    uploaded_photo_path = await _save_photo(photo_file)
    payload = {
        "name": name,
        "title": title,
        "experience_years": experience_years,
        "specialties": specialties,
        "bio": bio,
        "testimonial_summary": testimonial_summary.strip(),
        "contact_details": contact_details.strip(),
        "photo_url": uploaded_photo_path or photo_url,
        "document_url": uploaded_document_path or document_url.strip(),
        "active": _normalize_bool(active),
    }
    db = get_db()
    if not update_doctor(db, doctor_id, payload):
        return RedirectResponse(url="/admin?message=Doctor+not+found", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?message=Doctor+updated", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/doctors/{doctor_id}/status")
def update_doctor_status(doctor_id: str, request: Request, active: str = Form(...)) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    role_redirect = _admin_role_required(request)
    if role_redirect:
        return role_redirect

    db = get_db()
    if not update_doctor_status_record(db, doctor_id, _normalize_bool(active)):
        return RedirectResponse(url="/admin?message=Doctor+not+found", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?message=Doctor+status+updated", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/availability")
def add_availability(
    request: Request,
    doctor_id: str = Form(...),
    selected_days: list[str] = Form([]),
    specific_date: str = Form(""),
    start_time: str = Form(...),
    end_time: str = Form(...),
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    role_redirect = _admin_role_required(request)
    if role_redirect:
        return role_redirect

    if start_time >= end_time:
        return RedirectResponse(url="/admin?message=End+time+must+be+after+start+time", status_code=status.HTTP_303_SEE_OTHER)

    labels = list(selected_days)
    if specific_date.strip():
        labels.append(f"Date: {specific_date.strip()}")
    if not labels:
        return RedirectResponse(url="/admin?message=Select+at+least+one+day+or+date", status_code=status.HTTP_303_SEE_OTHER)

    db = get_db()
    created_count = 0
    for label in labels:
        payload = AvailabilityCreate(doctor_id=doctor_id, day_label=label, time_range=f"{start_time} - {end_time}")
        if add_availability_record(db, payload.model_dump()):
            created_count += 1

    if created_count == 0:
        return RedirectResponse(url="/admin?message=Invalid+doctor+selection", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url=f"/admin?message={created_count}+availability+slot(s)+saved", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/reviews")
def add_review(
    request: Request,
    patient_name: str = Form(...),
    location: str = Form(...),
    quote: str = Form(...),
    rating: int = Form(...),
    video_url: str = Form(""),
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    role_redirect = _admin_role_required(request)
    if role_redirect:
        return role_redirect

    db = get_db()
    payload = ReviewCreate(
        patient_name=patient_name,
        location=location,
        quote=quote,
        rating=rating,
        video_url=video_url,
    )
    add_review_record(db, payload.model_dump())
    return _message_redirect("/admin/reviews", "Review saved")


@router.post("/reviews/{review_id}/edit")
def edit_review(
    review_id: str,
    request: Request,
    patient_name: str = Form(...),
    location: str = Form(...),
    quote: str = Form(...),
    rating: int = Form(...),
    video_url: str = Form(""),
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    role_redirect = _admin_role_required(request)
    if role_redirect:
        return role_redirect

    db = get_db()
    if not update_review_record(
        db,
        review_id,
        {
            "patient_name": patient_name,
            "location": location,
            "quote": quote,
            "rating": rating,
            "video_url": video_url,
        },
    ):
        return _message_redirect("/admin/reviews", "Review not found")
    return _message_redirect("/admin/reviews", "Review updated")


@router.post("/services")
def add_service(request: Request, title: str = Form(...), description: str = Form(...)) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    role_redirect = _admin_role_required(request)
    if role_redirect:
        return role_redirect

    db = get_db()
    if not add_service_record(db, title, description):
        return RedirectResponse(url="/admin?message=Service+already+exists+or+invalid", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?message=Service+added", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/services/{service_id}/edit")
def edit_service(
    service_id: str,
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    role_redirect = _admin_role_required(request)
    if role_redirect:
        return role_redirect

    db = get_db()
    if not update_service_record(db, service_id, title, description):
        return RedirectResponse(url="/admin?message=Service+not+found", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?message=Service+updated", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/cities")
def add_city(request: Request, name: str = Form(...)) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    role_redirect = _admin_role_required(request)
    if role_redirect:
        return role_redirect

    db = get_db()
    if not add_city_record(db, name):
        return RedirectResponse(url="/admin?message=City+already+exists+or+invalid", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?message=City+added", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/cities/{city_id}/edit")
def edit_city(city_id: str, request: Request, name: str = Form(...)) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    role_redirect = _admin_role_required(request)
    if role_redirect:
        return role_redirect

    db = get_db()
    if not update_city_record(db, city_id, name):
        return RedirectResponse(url="/admin?message=City+not+found", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?message=City+updated", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/appointments/{appointment_id}/status")
async def update_appointment_status(
    appointment_id: str,
    request: Request,
    status_value: str = Form(...),
    diagnosis_details: str = Form(""),
    completion_notes: str = Form(""),
    follow_up_duration: str = Form(""),
    payment_status: str = Form("Pending"),
    payment_details: str = Form(""),
    doctor_id: str = Form(""),
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    return await _apply_appointment_update(
        request,
        appointment_id,
        status_value=status_value,
        diagnosis_details=diagnosis_details,
        completion_notes=completion_notes,
        follow_up_duration=follow_up_duration,
        payment_status=payment_status,
        payment_details=payment_details,
        doctor_id=doctor_id,
        redirect_to_detail=False,
    )


@router.post("/appointments/{appointment_id}/update")
async def update_appointment_detail(
    appointment_id: str,
    request: Request,
    status_value: str = Form(...),
    diagnosis_details: str = Form(""),
    completion_notes: str = Form(""),
    follow_up_duration: str = Form(""),
    payment_status: str = Form("Pending"),
    payment_details: str = Form(""),
    doctor_id: str = Form(""),
) -> RedirectResponse:
    redirect = _admin_required(request)
    if redirect:
        return redirect
    return await _apply_appointment_update(
        request,
        appointment_id,
        status_value=status_value,
        diagnosis_details=diagnosis_details,
        completion_notes=completion_notes,
        follow_up_duration=follow_up_duration,
        payment_status=payment_status,
        payment_details=payment_details,
        doctor_id=doctor_id,
        redirect_to_detail=True,
    )
