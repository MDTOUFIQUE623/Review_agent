import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

_client = None

def _get_client():
    # ponytail: lazy init, one client for the process lifetime
    global _client
    if _client is None:
        _client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    return _client

REVIEW_URL = "https://search.google.com/local/writereview?placeid={place_id}".format(
    place_id=os.getenv("GOOGLE_PLACE_ID", "")
)

def send_review_request(customer_name: str, to_phone: str, business_name: str, job_type: str) -> str:
    """Send WhatsApp review request. Returns Twilio message SID."""
    msg = (
        f"Hi {customer_name}! 👋 Thank you for choosing {business_name} for your {job_type} today.\n\n"
        f"We'd love to hear your feedback! Could you take 1 minute to leave us a Google review?\n\n"
        f"👉 {REVIEW_URL}\n\n"
        f"It really helps us grow. Thank you! 🙏"
    )
    message = _get_client().messages.create(
        from_=os.getenv("TWILIO_WHATSAPP_FROM"),
        to=f"whatsapp:{to_phone}",
        body=msg,
    )
    return message.sid


if __name__ == "__main__":
    # quick smoke test — prints SID if creds are valid, errors if not
    load_dotenv()
    import sys
    phone = sys.argv[1] if len(sys.argv) > 1 else input("Test phone (e.g. +919876543210): ")
    sid = send_review_request("Test User", phone, "Test Business", "AC Repair")
    print(f"OK — message SID: {sid}")

def send_raw(to_phone: str, message: str) -> str:
    """Send any plain message — used for owner alerts."""
    msg = _get_client().messages.create(
        from_=os.getenv("TWILIO_WHATSAPP_FROM"),
        to=f"whatsapp:{to_phone}",
        body=message,
    )
    return msg.sid