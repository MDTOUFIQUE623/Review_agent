import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

_client = None


def _get_client():
    """Lazy init Twilio client."""
    global _client

    if _client is None:
        _client = Client(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN"),
        )

    return _client


def send_review_request(
    customer_name: str,
    to_phone: str,
    business_name: str,
    job_type: str,
    google_place_id: str,
) -> str:
    """
    Send WhatsApp review request.
    Returns Twilio message SID.
    """

    review_url = (
        f"https://search.google.com/local/writereview?placeid={google_place_id}"
    )

    msg = (
        f"Hi {customer_name}! 👋 Thank you for choosing {business_name} "
        f"for your {job_type} today.\n\n"
        f"We'd love to hear your feedback! Could you take 1 minute to leave us a Google review?\n\n"
        f"👉 {review_url}\n\n"
        f"It really helps us grow. Thank you! 🙏"
    )

    message = _get_client().messages.create(
        from_=os.getenv("TWILIO_WHATSAPP_FROM"),
        to=f"whatsapp:{to_phone}",
        body=msg,
    )

    return message.sid


def send_raw(to_phone: str, message: str) -> str:
    """
    Send any plain WhatsApp message.
    Used for owner notifications and alerts.
    """

    msg = _get_client().messages.create(
        from_=os.getenv("TWILIO_WHATSAPP_FROM"),
        to=f"whatsapp:{to_phone}",
        body=message,
    )

    return msg.sid


if __name__ == "__main__":
    import sys

    phone = (
        sys.argv[1]
        if len(sys.argv) > 1
        else input("Test phone (e.g. +919876543210): ")
    )

    sid = send_review_request(
        customer_name="Test User",
        to_phone=phone,
        business_name="Test Business",
        job_type="AC Repair",
        google_place_id="ChIJ9Wl0S2AUrjsRNI2PQmBxT_Y",
    )

    print(f"OK — message SID: {sid}")