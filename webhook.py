import os
import hmac
import hashlib
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, JSONResponse
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

# ── Meta webhook verification (GET) ──────────────────────────────────────────

@router.get("/webhook")
async def meta_verify(request: Request):
    """Meta sends a GET to verify the webhook endpoint."""
    params = dict(request.query_params)
    verify_token = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "reviewagent_verify")
    if (params.get("hub.mode") == "subscribe" and
            params.get("hub.verify_token") == verify_token):
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)

# ── Parsers ───────────────────────────────────────────────────────────────────

async def _parse_twilio(request: Request) -> tuple[str, str] | tuple[None, None]:
    """Extract phone + reply from Twilio form POST."""
    form = await request.form()
    print(f"[webhook/twilio] incoming: {dict(form)}")
    phone = form.get("From", "").replace("whatsapp:", "").strip()
    reply = form.get("Body", "").strip()
    return (phone, reply) if phone and reply else (None, None)

async def _parse_meta(body: dict) -> tuple[str, str] | tuple[None, None]:
    """Extract phone + reply from Meta Cloud API JSON payload."""
    print(f"[webhook/meta] incoming: {body}")
    try:
        entry    = body["entry"][0]
        change   = entry["changes"][0]
        value    = change["value"]

        # ignore status updates (delivered, read receipts)
        if "statuses" in value and "messages" not in value:
            return None, None

        msg      = value["messages"][0]
        phone    = "+" + msg["from"]
        reply    = msg.get("text", {}).get("body", "").strip()
        return (phone, reply) if reply else (None, None)
    except (KeyError, IndexError):
        return None, None

# ── Core handler ──────────────────────────────────────────────────────────────

async def _handle(phone: str, reply: str):
    """Shared logic after phone + reply are extracted from any provider."""
    with db.conn() as c:
        cur = db._cur(c)
        cur.execute(
            f"""SELECT r.*, b.owner_phone, b.name AS business_name,
                       b.google_place_id, b.provider, b.provider_config
                FROM reviews r
                JOIN businesses b ON r.business_id = b.id
                WHERE r.customer_phone = {db.PH}
                ORDER BY r.sent_at DESC LIMIT 1""",
            (phone,)
        )
        rows = db._rows(cur)
        row = rows[0] if rows else None

    if not row:
        print(f"[webhook] no row for phone: {phone}")
        return

    if row["status"] in TERMINAL:
        print(f"[webhook] row {row['id']} already {row['status']}, ignoring")
        return

    # 1. Classify
    label = classifier.classify(reply)
    db.log_reply(row["id"], reply, status=label)
    print(f"[webhook] row {row['id']} → {label}")

    # 2. Auto-reply to customer via same provider they received from
    try:
        whatsapp.send_raw(phone, AUTO_REPLIES[label], business=dict(row))
        print(f"[webhook] auto-reply sent ({label})")
    except Exception as ex:
        print(f"[webhook] auto-reply failed: {ex}")

    # 3. Alert owner on complaint — via their business provider
    if label == "complaint":
        alert = (
            f"⚠️ Complaint!\n"
            f"Customer: {row['customer_name']} ({phone})\n"
            f"Business: {row['business_name']} | Job: {row['job_type']}\n"
            f"Message: \"{reply}\""
        )
        try:
            whatsapp.send_raw(row["owner_phone"], alert, business=dict(row))
            print(f"[webhook] owner alerted at {row['owner_phone']}")
        except Exception as ex:
            print(f"[webhook] owner alert failed: {ex}")

# ── Single POST endpoint — routes by Content-Type ─────────────────────────────

@router.post("/webhook")
async def receive_reply(request: Request):
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        # Meta Cloud API
        body = await request.json()
        
        # ponytail: handle Meta status callbacks (delivered, read) first
        try:
            entry = body["entry"][0]
            change = entry["changes"][0]
            value = change["value"]
            if "statuses" in value:
                status_obj = value["statuses"][0]
                sid = status_obj["id"]
                status = status_obj["status"]
                db.update_status_by_sid(sid, status)
                print(f"[webhook/meta] status update: {sid} -> {status}")
                return JSONResponse({"status": "ok"})
        except (KeyError, IndexError):
            pass

        phone, reply = await _parse_meta(body)
        if phone and reply:
            await _handle(phone, reply)
        return JSONResponse({"status": "ok"})  # Meta expects 200 JSON

    else:
        # Twilio (application/x-www-form-urlencoded)
        phone, reply = await _parse_twilio(request)
        if phone and reply:
            await _handle(phone, reply)
        return PlainTextResponse("")  # Twilio expects 200 empty