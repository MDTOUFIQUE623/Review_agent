from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import whatsapp
import db

TERMINAL = {"positive", "complaint", "unsubscribe", "closed"}

def _followup_msg(name, job_type, place_id):
    return (
        f"Hi {name}! 👋 Just a quick reminder — we'd love your feedback on your recent {job_type}.\n\n"
        f"Only takes 1 minute:\n"
        f"👉 https://search.google.com/local/writereview?placeid={place_id}\n\n"
        f"Thank you! 🙏"
    )

def _final_msg(name, job_type, business_name, place_id):
    return (
        f"Hi {name}, last message from us! If you have a moment, your review of our {job_type} "
        f"service would mean a lot to {business_name}:\n"
        f"👉 https://search.google.com/local/writereview?placeid={place_id}\n"
        f"Thank you! 🙏"
    )

def run_checks():
    print(f"[scheduler] running checks at {datetime.utcnow().isoformat()}")

    # Day 3 — first follow-up
    for r in db.get_pending_followups(days=3, follow_up_sent=0):
        try:
            whatsapp.send_raw(
                r["customer_phone"],
                _followup_msg(r["customer_name"], r["job_type"], r["google_place_id"])
            )
            with db.conn() as c:
                cur = db._cur(c)
                cur.execute(f"UPDATE reviews SET follow_up_sent=1 WHERE id={db.PH}", (r["id"],))
            print(f"[scheduler] day-3 follow-up → row {r['id']}")
        except Exception as e:
            print(f"[scheduler] day-3 failed row {r['id']}: {e}")

    # Day 7 — final nudge then close
    for r in db.get_pending_followups(days=7, follow_up_sent=1):
        try:
            whatsapp.send_raw(
                r["customer_phone"],
                _final_msg(r["customer_name"], r["job_type"], r["business_name"], r["google_place_id"])
            )
            with db.conn() as c:
                cur = db._cur(c)
                cur.execute(
                    f"UPDATE reviews SET follow_up_sent=2, status='closed' WHERE id={db.PH}",
                    (r["id"],)
                )
            print(f"[scheduler] day-7 final → row {r['id']}")
        except Exception as e:
            print(f"[scheduler] day-7 failed row {r['id']}: {e}")

    # Daily — process any businesses past grace period
    db.process_deactivations()

def start():
    s = BackgroundScheduler()
    s.add_job(run_checks, "interval", hours=1, next_run_time=datetime.now())
    s.start()
    print("[scheduler] started — checks every hour")
    return s