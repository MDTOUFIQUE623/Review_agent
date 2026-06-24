import sqlite3
from contextlib import contextmanager
import re

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

def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:40]

def init(db=None):
    with conn(db) as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS businesses (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT NOT NULL,
                owner_phone      TEXT NOT NULL,
                google_place_id  TEXT NOT NULL,
                slug             TEXT UNIQUE,
                active           INTEGER DEFAULT 1,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id     INTEGER NOT NULL REFERENCES businesses(id),
                customer_name   TEXT,
                customer_phone  TEXT,
                job_type        TEXT DEFAULT 'Visit',
                sent_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status          TEXT DEFAULT 'pending',
                reply_text      TEXT,
                follow_up_sent  INTEGER DEFAULT 0,
                whatsapp_sid    TEXT
            );
        """)

# ── Businesses ────────────────────────────────────────────────────────────────

def add_business(name, owner_phone, google_place_id, db=None):
    slug = _slugify(name)
    with conn(db) as c:
        # ensure unique slug
        existing = [r[0] for r in c.execute("SELECT slug FROM businesses WHERE slug LIKE ?", (slug + "%",))]
        if slug in existing:
            slug = f"{slug}-{len(existing)}"
        cur = c.execute(
            "INSERT INTO businesses (name, owner_phone, google_place_id, slug) VALUES (?,?,?,?)",
            (name, owner_phone, google_place_id, slug)
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

def get_business_by_slug(slug, db=None):
    with conn(db) as c:
        row = c.execute("SELECT * FROM businesses WHERE slug=? AND active=1", (slug,)).fetchone()
        return dict(row) if row else None

# ── Reviews ───────────────────────────────────────────────────────────────────

def insert(business_id, customer_name, customer_phone, job_type="Visit", db=None):
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
        b1 = add_business("Cafe Blue", "+919999999991", "ChIJtest1", tmp)
        b2 = add_business("Cafe Blue", "+919999999992", "ChIJtest2", tmp)  # duplicate name
        biz1 = get_business(b1, tmp)
        biz2 = get_business(b2, tmp)
        assert biz1["slug"] == "cafe-blue"
        assert biz2["slug"] != biz1["slug"]  # unique slug
        biz_by_slug = get_business_by_slug("cafe-blue", tmp)
        assert biz_by_slug["id"] == b1
        print(f"OK — slugs: {biz1['slug']}, {biz2['slug']}")
    finally:
        os.unlink(tmp)