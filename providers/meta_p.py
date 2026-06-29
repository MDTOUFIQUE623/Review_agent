import os
import httpx

# Meta Cloud API endpoint
META_API = "https://graph.facebook.com/v19.0/{phone_number_id}/messages"

def _headers():
    token = os.getenv("META_ACCESS_TOKEN")
    if not token:
        raise ValueError("META_ACCESS_TOKEN not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

def _phone_id(config: dict) -> str:
    return config.get("phone_number_id") or os.getenv("META_PHONE_NUMBER_ID", "")

def send(to_phone: str, message: str, config: dict = None) -> str:
    """Send free-form text — only works within 24hr customer service window."""
    config = config or {}
    phone_id = _phone_id(config)
    to = to_phone.lstrip("+")

    resp = httpx.post(
        META_API.format(phone_number_id=phone_id),
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        },
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("messages", [{}])[0].get("id", "sent")

def send_template(
    to_phone: str,
    template_name: str,
    variables: list,
    config: dict = None,
) -> str:
    """
    Send approved WhatsApp template via Meta Cloud API.
    variables = [customer_name, business_name, job_type, review_url]
    Maps to {{1}} {{2}} {{3}} {{4}} in the template.
    """
    config = config or {}
    phone_id = _phone_id(config)
    to = to_phone.lstrip("+")

    components = [{
        "type": "body",
        "parameters": [
            {"type": "text", "text": str(v)} for v in variables
        ]
    }]

    resp = httpx.post(
        META_API.format(phone_number_id=phone_id),
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en"},
                "components": components,
            },
        },
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("messages", [{}])[0].get("id", "sent")