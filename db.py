import sqlite3
from contextlib import contextmanager

DB = "reviews.db"

@contextmanager
def conn(db=None):
    c = sqlite3.connect(db or DB)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init(db=None):
    with conn(db) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name   TEXT,
                customer_phone  TEXT,
                business_name   TEXT,
                job_type        TEXT,
                sent_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status          TEXT DEFAULT 'pending',
                reply_text      TEXT,
                follow_up_sent  INTEGER DEFAULT 0,
                whatsapp_sid    TEXT
            )
        """)

def insert(customer_name, customer_phone, business_name, job_type, db=None):
    with conn(db) as c:
        cur = c.execute(
            "INSERT INTO reviews (customer_name, customer_phone, business_name, job_type) VALUES (?,?,?,?)",
            (customer_name, customer_phone, business_name, job_type)
        )
        return cur.lastrowid

def all_rows(db=None):
    with conn(db) as c:
        return [dict(r) for r in c.execute("SELECT * FROM reviews ORDER BY sent_at DESC")]


if __name__ == "__main__":
    import tempfile, os
    tmp = tempfile.mktemp(suffix=".db")
    try:
        init(tmp)
        row_id = insert("Test Customer", "+919999999999", "Cafe Blue", "AC Repair", tmp)
        rows = all_rows(tmp)
        assert len(rows) == 1
        assert rows[0]["customer_name"] == "Test Customer"
        assert rows[0]["status"] == "pending"
        print(f"OK — inserted row id={row_id}, status={rows[0]['status']}")
    finally:
        os.unlink(tmp)

def update_status(row_id: int, status: str, whatsapp_sid: str = None, db=None):
    with conn(db) as c:
        c.execute(
            "UPDATE reviews SET status=?, whatsapp_sid=? WHERE id=?",
            (status, whatsapp_sid, row_id)
        )