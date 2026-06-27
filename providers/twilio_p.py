import os
from twilio.rest import Client

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = Client(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN"),
        )
    return _client

def send(to_phone: str, message: str, config: dict = None) -> str:
    """Send free-form WhatsApp message via Twilio. Returns SID."""
    from_number = (config or {}).get("from", os.getenv("TWILIO_WHATSAPP_FROM"))
    msg = _get_client().messages.create(
        from_=from_number,
        to=f"whatsapp:{to_phone}",
        body=message,
    )
    return msg.sid

def send_template(
    to_phone: str,
    template_name: str,
    variables: list,
    config: dict = None,
) -> str:
    """
    Twilio doesn't use Meta templates for sandbox.
    Falls back to free-form with variables joined.
    In production with approved sender, use content_sid instead.
    """
    # ponytail: for now just send free-form — swap to content_sid when needed
    message = " ".join(str(v) for v in variables)
    return send(to_phone, message, config)