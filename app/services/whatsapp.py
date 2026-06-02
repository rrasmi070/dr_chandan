from __future__ import annotations

import httpx

from app.config import (
    WHATSAPP_ACCESS_NUMBER,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_PROVIDER,
    WHATSAPP_TOKEN,
)


async def send_status_update(phone: str, patient_name: str, status: str) -> tuple[bool, str]:
    if WHATSAPP_PROVIDER.lower() != "meta":
        return False, "WhatsApp provider is not configured."

    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_NUMBER:
        return False, "WhatsApp credentials are incomplete."

    url = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {
            "body": (
                f"Hello {patient_name}, your Physiophyte Medicare appointment status is now "
                f"{status}. Reply to this message if you need assistance."
            )
        },
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload, headers=headers)

    if response.is_success:
        return True, "WhatsApp status update sent."

    return False, f"WhatsApp send failed: {response.text}"
