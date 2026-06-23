from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import whatsapp
import db

TERMINAL = {"positive", "complaint", "unsubscribe", "closed"}

FOLLOWUP_MSG = (
    "Hi {name}! 👋 Just a quick reminder — we'd love your feedback on our {job} service.\n\n"
    "It only takes 1 minute and really helps us grow:\n"
    "👉 {url}\n\n"
    "Thank you! 🙏"
)

FINAL_MSG = (
    "Hi {name}, this is our last message! If you have a moment, we'd really appreciate "
    "a Google review for your recent {job} service:\n"
    "👉 {url}\n"
    "Thank you for choosing {business}! 🙏"
)

def _send_followups():
    now = datetime.utcnow()
    with db.conn() as c:
        rows = c.execute(
            "SELECT * FROM reviews WHERE status='sent' AND sent_at <= ? AND follow_up_sent = 0",
            ((now - timedelta(days=3)).isoformat(),)
        ).fetchall()

    for r in rows:
        try:
            msg = FOLLOWUP_MSG.format(
                name=r["customer_name"], job=r["job_type"], url=whatsapp.REVIEW_URL
            )
            whatsapp.send_raw(r["customer_phone"], msg)
            with db.conn() as c:
                c.execute("UPDATE reviews SET follow_up_sent=1 WHERE id=?", (r["id"],))
            print(f"[scheduler] follow-up sent to {r['customer_phone']} (row {r['id']})")
        except Exception as e:
            print(f"[scheduler] follow-up failed for row {r['id']}: {e}")

def _send_finals():
    now = datetime.utcnow()
    with db.conn() as c:
        rows = c.execute(
            "SELECT * FROM reviews WHERE status='sent' AND sent_at <= ? AND follow_up_sent = 1",
            ((now - timedelta(days=7)).isoformat(),)
        ).fetchall()

    for r in rows:
        try:
            msg = FINAL_MSG.format(
                name=r["customer_name"], job=r["job_type"],
                url=whatsapp.REVIEW_URL, business=r["business_name"]
            )
            whatsapp.send_raw(r["customer_phone"], msg)
            with db.conn() as c:
                c.execute("UPDATE reviews SET follow_up_sent=2, status='closed' WHERE id=?", (r["id"],))
            print(f"[scheduler] final nudge sent to {r['customer_phone']} (row {r['id']})")
        except Exception as e:
            print(f"[scheduler] final nudge failed for row {r['id']}: {e}")

def run_checks():
    """Called by APScheduler every hour."""
    print(f"[scheduler] running checks at {datetime.utcnow().isoformat()}")
    _send_followups()
    _send_finals()

def start():
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_checks, "interval", hours=1, next_run_time=datetime.now())
    scheduler.start()
    print("[scheduler] started — checks every hour")
    return scheduler