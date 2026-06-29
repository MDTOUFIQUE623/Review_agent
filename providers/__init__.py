"""
Provider router — picks the right WhatsApp provider per business.
Add new providers here without touching anything else.
"""
import json
from . import twilio_p, interakt_p, meta_p

PROVIDERS = {
    "twilio":   twilio_p,
    "interakt": interakt_p,  # hidden from UI, kept for future use
    "meta":     meta_p,
}

def _provider(name: str):
    p = PROVIDERS.get(name)
    if not p:
        raise ValueError(f"Unknown provider: {name}. Choose from: {list(PROVIDERS)}")
    return p

def _config(business: dict) -> dict:
    """Parse provider_config JSON from business row."""
    raw = business.get("provider_config") or "{}"
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}

def send_review_request(
    customer_name: str,
    to_phone: str,
    business_name: str,
    job_type: str,
    google_place_id: str,
    business: dict,
) -> str:
    """Send first review request — uses template for Interakt, free-form for Twilio."""
    provider_name = business.get("provider", "twilio")
    p = _provider(provider_name)
    config = _config(business)
    review_url = f"https://search.google.com/local/writereview?placeid={google_place_id}"

    if provider_name in ("interakt", "meta"):
        template_name = config.get("template_name", "review_request")
        return p.send_template(
            to_phone=to_phone,
            template_name=template_name,
            variables=[customer_name, business_name, job_type, review_url],
            config=config,
        )

    # Twilio and any other provider — free-form
    message = (
        f"Hi {customer_name}! 👋 Thank you for choosing {business_name} "
        f"for your {job_type} today.\n\n"
        f"We'd love your feedback! Could you take 1 minute to leave us a Google review?\n\n"
        f"👉 {review_url}\n\n"
        f"It really helps us grow. Thank you! 🙏"
    )
    return p.send(to_phone, message, config)

def send_raw(to_phone: str, message: str, business: dict) -> str:
    """Send any free-form message — used for auto-replies, follow-ups, owner alerts."""
    provider_name = business.get("provider", "twilio")
    p = _provider(provider_name)
    config = _config(business)
    return p.send(to_phone, message, config)