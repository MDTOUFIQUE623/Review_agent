import os
import base64
import httpx

INTERAKT_API = "https://api.interakt.ai/v1/public/message/"

def _auth_header(api_key: str) -> str:
    """Interakt uses Basic auth with base64-encoded API key."""
    return "Basic " + base64.b64encode(api_key.encode()).decode()

def send(to_phone: str, message: str, config: dict = None) -> str:
    """
    Send free-form WhatsApp message via Interakt.
    Only works within 24hr customer service window.
    Returns Interakt message id.
    """
    api_key = (config or {}).get("api_key") or os.getenv("INTERAKT_API_KEY")
    if not api_key:
        raise ValueError("Interakt API key not set")

    # Strip country code for Interakt (expects number without +91)
    phone = to_phone.lstrip("+")
    country_code = "91" if phone.startswith("91") else "1"
    number = phone[len(country_code):]

    payload = {
        "countryCode": f"+{country_code}",
        "phoneNumber": number,
        "callbackData": "free_form",
        "type": "Text",
        "data": {"message": message},
    }

    resp = httpx.post(
        INTERAKT_API,
        json=payload,
        headers={
            "Authorization": _auth_header(api_key),
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("id", "sent")

def send_template(
    to_phone: str,
    template_name: str,
    variables: list,
    config: dict = None,
) -> str:
    """
    Send approved WhatsApp template via Interakt.
    This is required for the FIRST message to any new customer.
    variables = [customer_name, business_name, job_type, review_url]
    """
    api_key = (config or {}).get("api_key") or os.getenv("INTERAKT_API_KEY")
    if not api_key:
        raise ValueError("Interakt API key not set")

    phone = to_phone.lstrip("+")
    country_code = "91" if phone.startswith("91") else "1"
    number = phone[len(country_code):]

    payload = {
        "countryCode": f"+{country_code}",
        "phoneNumber": number,
        "callbackData": "review_request",
        "type": "Template",
        "template": {
            "name": template_name,
            "languageCode": "en",
            "bodyValues": [str(v) for v in variables],
        },
    }

    resp = httpx.post(
        INTERAKT_API,
        json=payload,
        headers={
            "Authorization": _auth_header(api_key),
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("id", "sent")