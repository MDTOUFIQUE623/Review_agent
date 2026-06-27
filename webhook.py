from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import db
import classifier
import whatsapp

router = APIRouter()

TERMINAL = {"positive", "complaint", "unsubscribe", "closed"}

AUTO_REPLIES = {
    "positive": (
        "Thank you so much! 🌟 Your kind words mean the world to us.\n"
        "We'd love to see your Google review when you get a chance — it really helps us grow! 🙏"
    ),
    "complaint": (
        "We're really sorry to hear about your experience 😔\n"
        "Our team has been notified and will reach out to you shortly to make things right."
    ),
    "unsubscribe": (
        "No problem at all! You won't receive any more messages from us.\n"
        "Sorry for any inconvenience. 🙏"
    ),
    "other": (
        "Thanks for your message! 😊 We hope you had a great experience with us.\n"
        "Feel free to reach out anytime!"
    ),
}

@router.post("/webhook", response_class=PlainTextResponse)
async def receive_reply(request: Request):
    form = await request.form()
    print(f"[webhook] incoming: {dict(form)}")

    phone = form.get("From", "").replace("whatsapp:", "").strip()
    reply = form.get("Body", "").strip()
    if not phone or not reply:
        return ""

    with db.conn() as c:
        cur = db._cur(c)

        cur.execute(
            f"""
            SELECT
                r.*,
                b.owner_phone,
                b.name AS business_name,
                b.google_place_id,
                b.provider,
                b.provider_config
            FROM reviews r
            JOIN businesses b
                ON r.business_id = b.id
            WHERE r.customer_phone = {db.PH}
            ORDER BY r.sent_at DESC
            LIMIT 1
            """,
            (phone,),
        )

        rows = db._rows(cur)
        row = rows[0] if rows else None

    if not row:
        print(f"[webhook] no row for phone: {phone}")
        return ""

    if row["status"] in TERMINAL:
        print(f"[webhook] row {row['id']} already {row['status']}, ignoring")
        return ""

    # 1. Classify
    label = classifier.classify(reply)
    db.log_reply(row["id"], reply, status=label)
    print(f"[webhook] row {row['id']} → {label}")

    # 2. Auto-reply to customer
    try:
        whatsapp.send_raw(phone, AUTO_REPLIES[label], row)
        print(f"[webhook] auto-reply sent ({label})")
    except Exception as e:
        print(f"[webhook] auto-reply failed: {e}")

    # 3. Alert owner on complaint
    if label == "complaint":
        alert = (
            f"⚠️ Complaint!\n"
            f"Customer: {row['customer_name']} ({phone})\n"
            f"Business: {row['business_name']} | Job: {row['job_type']}\n"
            f"Message: \"{reply}\""
        )
        try:
            whatsapp.send_raw(row["owner_phone"], alert)
            print(f"[webhook] owner alerted at {row['owner_phone']}")
        except Exception as e:
            print(f"[webhook] owner alert failed: {e}")

    return ""