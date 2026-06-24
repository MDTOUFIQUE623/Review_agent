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
        c.executescript("""
            CREATE TABLE IF NOT EXISTS businesses (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT NOT NULL,
                owner_phone      TEXT NOT NULL,
                google_place_id  TEXT NOT NULL,
                active           INTEGER DEFAULT 1,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id     INTEGER NOT NULL REFERENCES businesses(id),
                customer_name   TEXT,
                customer_phone  TEXT,
                job_type        TEXT,
                sent_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status          TEXT DEFAULT 'pending',
                reply_text      TEXT,
                follow_up_sent  INTEGER DEFAULT 0,
                whatsapp_sid    TEXT
            );
        """)

# ── Businesses ────────────────────────────────────────────────────────────────

def add_business(name, owner_phone, google_place_id, db=None):
    with conn(db) as c:
        cur = c.execute(
            "INSERT INTO businesses (name, owner_phone, google_place_id) VALUES (?,?,?)",
            (name, owner_phone, google_place_id)
        )
        return cur.lastrowid

def get_businesses(db=None):
    with conn(db) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM businesses WHERE active=1 ORDER BY name"
        )]

def get_business(business_id, db=None):
    with conn(db) as c:
        row = c.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
        return dict(row) if row else None

# ── Reviews ───────────────────────────────────────────────────────────────────

def insert(business_id, customer_name, customer_phone, job_type, db=None):
    with conn(db) as c:
        cur = c.execute(
            "INSERT INTO reviews (business_id, customer_name, customer_phone, job_type) VALUES (?,?,?,?)",
            (business_id, customer_name, customer_phone, job_type)
        )
        return cur.lastrowid

def update_status(row_id, status, whatsapp_sid=None, db=None):
    with conn(db) as c:
        c.execute(
            "UPDATE reviews SET status=?, whatsapp_sid=? WHERE id=?",
            (status, whatsapp_sid, row_id)
        )

def log_reply(row_id, reply_text, status="replied", db=None):
    with conn(db) as c:
        c.execute(
            "UPDATE reviews SET reply_text=?, status=? WHERE id=?",
            (reply_text, status, row_id)
        )

def all_rows(business_id=None, db=None):
    with conn(db) as c:
        if business_id:
            return [dict(r) for r in c.execute(
                "SELECT r.*, b.name as business_name FROM reviews r "
                "JOIN businesses b ON r.business_id = b.id "
                "WHERE r.business_id=? ORDER BY r.sent_at DESC", (business_id,)
            )]
        return [dict(r) for r in c.execute(
            "SELECT r.*, b.name as business_name FROM reviews r "
            "JOIN businesses b ON r.business_id = b.id "
            "ORDER BY r.sent_at DESC"
        )]

def get_pending_followups(days, follow_up_sent, db=None):
    """Rows that are still 'sent' and haven't had follow_up_sent level yet."""
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with conn(db) as c:
        return [dict(r) for r in c.execute(
            "SELECT r.*, b.name as business_name, b.owner_phone, b.google_place_id "
            "FROM reviews r JOIN businesses b ON r.business_id = b.id "
            "WHERE r.status='sent' AND r.sent_at <= ? AND r.follow_up_sent=?",
            (cutoff, follow_up_sent)
        )]


if __name__ == "__main__":
    import tempfile, os
    tmp = tempfile.mktemp(suffix=".db")
    try:
        init(tmp)

        # add two businesses
        b1 = add_business("Cafe Blue", "+919999999991", "ChIJtest1", tmp)
        b2 = add_business("Wetalk AC", "+919999999992", "ChIJtest2", tmp)

        # add reviews for each
        r1 = insert(b1, "Rahul", "+911111111111", "Coffee", tmp)
        r2 = insert(b2, "Priya", "+912222222222", "AC Repair", tmp)

        # check isolation
        b1_rows = all_rows(business_id=b1, db=tmp)
        b2_rows = all_rows(business_id=b2, db=tmp)
        all_ = all_rows(db=tmp)

        assert len(b1_rows) == 1 and b1_rows[0]["customer_name"] == "Rahul"
        assert len(b2_rows) == 1 and b2_rows[0]["customer_name"] == "Priya"
        assert len(all_) == 2

        # check business lookup
        biz = get_business(b1, tmp)
        assert biz["name"] == "Cafe Blue"

        print(f"OK — businesses: {len(get_businesses(tmp))}, reviews: {len(all_)}")
        print(f"     b1 sees only: {[r['customer_name'] for r in b1_rows]}")
        print(f"     b2 sees only: {[r['customer_name'] for r in b2_rows]}")
    finally:
        os.unlink(tmp)