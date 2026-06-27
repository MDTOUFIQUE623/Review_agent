"""
Thin shim — kept for backward compat with scheduler/webhook.
All real logic lives in providers/.
"""
import os
from providers import send_review_request as _send_review_request
from providers import send_raw as _send_raw

# Default Twilio business dict for owner alerts (not tied to any client)
_TWILIO_DEFAULT = {
    "provider": "twilio",
    "provider_config": "{}",
}

def send_review_request(
    customer_name: str,
    to_phone: str,
    business_name: str,
    job_type: str,
    google_place_id: str,
    business: dict = None,
) -> str:
    return _send_review_request(
        customer_name, to_phone, business_name,
        job_type, google_place_id,
        business or _TWILIO_DEFAULT,
    )

def send_raw(to_phone: str, message: str, business: dict = None) -> str:
    return _send_raw(to_phone, message, business or _TWILIO_DEFAULT)