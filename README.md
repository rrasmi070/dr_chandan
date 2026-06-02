# Physiophyte Medicare Website

FastAPI website and admin panel for managing doctors, availability, appointments, and patient reviews with MongoDB as the primary database.

## Features

- Modular FastAPI routers (`app/routers/public.py` and `app/routers/admin.py`)
- Responsive public homepage and dedicated About Us page
- Admin dashboard with navbar sections for doctors, availability, services, reviews, cities, appointments, and admin users
- Add and edit doctor details with photo URL or uploaded photo file
- Auto-generated doctor employee ID (`DOC-0001` style)
- Add and edit physiotherapy services from admin panel
- Add and edit city list from admin panel (used by booking dropdown)
- Add and edit review library entries
- Booking form shows selected doctor availability before submit
- MongoDB storage using the connection string from environment variables
- Appointment status updates with pluggable WhatsApp integration

## Run locally

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment variables in `.env` if needed:

- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `SECRET_KEY`
- `MONGODB_URI`
- `MONGODB_DB_NAME`
- `WHATSAPP_PROVIDER`
- `WHATSAPP_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_ACCESS_NUMBER`

4. Start the app:

```bash
uvicorn app.main:app --reload
```

5. Open `http://127.0.0.1:8000`

## Logo

- Replace `static/images/logo.svg` with your final logo (or update templates to your preferred logo path).

## Admin login

Default credentials when env vars are not set:

- Username: `admin`
- Password: `admin123`
