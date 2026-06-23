from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import os
import db
import classifier
import whatsapp

router = APIRouter()

OWNER_PHONE = os.getenv("OWNER_PHONE")
TERMINAL = {"positive", "complaint", "unsubscribe", "closed"}

@router.post("/webhook", response_class=PlainTextResponse)
async def receive_reply(request: Request):
    form = await request.form()
    print(f"[webhook] incoming: {dict(form)}")

    phone = form.get("From", "").replace("whatsapp:", "").strip()
    reply = form.get("Body", "").strip()

    if not phone or not reply:
        return ""

    with db.conn() as c:
        row = c.execute(
            "SELECT id, customer_name, business_name, job_type, status FROM reviews "
            "WHERE customer_phone=? ORDER BY sent_at DESC LIMIT 1",
            (phone,)
        ).fetchone()

    if not row:
        print(f"[webhook] no row found for phone: {phone}")
        return ""

    # Don't overwrite terminal statuses
    if row["status"] in TERMINAL:
        print(f"[webhook] row {row['id']} already terminal ({row['status']}), ignoring")
        return ""

    label = classifier.classify(reply)
    db.log_reply(row["id"], reply, status=label)
    print(f"[webhook] row {row['id']} classified as: {label}")

    if label == "complaint" and OWNER_PHONE:
        alert = (
            f"⚠️ Complaint received!\n"
            f"Customer: {row['customer_name']} ({phone})\n"
            f"Business: {row['business_name']} | Job: {row['job_type']}\n"
            f"Message: \"{reply}\""
        )
        try:
            whatsapp.send_raw(OWNER_PHONE, alert)
            print(f"[webhook] owner alerted at {OWNER_PHONE}")
        except Exception as e:
            print(f"[webhook] owner alert failed: {e}")

    return ""