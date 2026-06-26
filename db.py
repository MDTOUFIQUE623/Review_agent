import os
import re
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL")
POSTGRES = bool(DATABASE_URL)
PH = "%s" if POSTGRES else "?"

# ── Connection ────────────────────────────────────────────────────────────────

if POSTGRES:
    import psycopg2, psycopg2.extras

    @contextmanager
    def conn(db=None):
        c = psycopg2.connect(DATABASE_URL)
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _cur(c):
        return c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

else:
    import sqlite3

    @contextmanager
    def conn(db=None):
        c = sqlite3.connect(db or "reviews.db")
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _cur(c):
        return c.cursor()


def _rows(cur):
    rows = cur.fetchall()
    if not rows:
        return []
    return [dict(r) for r in rows]

# ── Schema ────────────────────────────────────────────────────────────────────

_ID  = "SERIAL" if POSTGRES else "INTEGER"

def init(db=None):
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS businesses (
                id               {_ID} PRIMARY KEY,
                name             TEXT NOT NULL,
                owner_phone      TEXT NOT NULL,
                google_place_id  TEXT NOT NULL,
                slug             TEXT UNIQUE,
                active           INTEGER DEFAULT 1,
                status           TEXT DEFAULT 'active',
                deactivate_at    TIMESTAMP,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS reviews (
                id              {_ID} PRIMARY KEY,
                business_id     INTEGER NOT NULL REFERENCES businesses(id),
                customer_name   TEXT,
                customer_phone  TEXT,
                job_type        TEXT DEFAULT 'Visit',
                sent_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status          TEXT DEFAULT 'pending',
                reply_text      TEXT,
                follow_up_sent  INTEGER DEFAULT 0,
                whatsapp_sid    TEXT
            )
        """)

# ── Slug ──────────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.lower().strip())
    return re.sub(r"[\s_-]+", "-", s)[:40]

# ── Businesses ────────────────────────────────────────────────────────────────

def add_business(name, owner_phone, google_place_id, db=None):
    slug = _slugify(name)
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(f"SELECT slug FROM businesses WHERE slug LIKE {PH}", (slug + "%",))
        existing = [r["slug"] for r in _rows(cur)]
        if slug in existing:
            slug = f"{slug}-{len(existing)}"
        cur.execute(
            f"INSERT INTO businesses (name, owner_phone, google_place_id, slug) "
            f"VALUES ({PH},{PH},{PH},{PH})",
            (name, owner_phone, google_place_id, slug)
        )

def get_businesses(db=None):
    with conn(db) as c:
        cur = _cur(c)
        cur.execute("SELECT * FROM businesses WHERE active=1 ORDER BY name")
        return _rows(cur)

def get_business(business_id, db=None):
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(f"SELECT * FROM businesses WHERE id={PH}", (business_id,))
        rows = _rows(cur)
        return rows[0] if rows else None

def get_business_by_slug(slug, db=None):
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(f"SELECT * FROM businesses WHERE slug={PH} AND active=1", (slug,))
        rows = _rows(cur)
        return rows[0] if rows else None

# ── Reviews ───────────────────────────────────────────────────────────────────

def insert(business_id, customer_name, customer_phone, job_type="Visit", db=None):
    with conn(db) as c:
        cur = _cur(c)
        sql = (
            f"INSERT INTO reviews (business_id, customer_name, customer_phone, job_type) "
            f"VALUES ({PH},{PH},{PH},{PH})"
        )
        if POSTGRES:
            cur.execute(sql + " RETURNING id", (business_id, customer_name, customer_phone, job_type))
            return _rows(cur)[0]["id"]
        else:
            cur.execute(sql, (business_id, customer_name, customer_phone, job_type))
            return cur.lastrowid

def update_status(row_id, status, whatsapp_sid=None, db=None):
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(
            f"UPDATE reviews SET status={PH}, whatsapp_sid={PH} WHERE id={PH}",
            (status, whatsapp_sid, row_id)
        )

def log_reply(row_id, reply_text, status="replied", db=None):
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(
            f"UPDATE reviews SET reply_text={PH}, status={PH} WHERE id={PH}",
            (reply_text, status, row_id)
        )

def all_rows(business_id=None, db=None):
    with conn(db) as c:
        cur = _cur(c)
        if business_id:
            cur.execute(
                f"SELECT r.*, b.name as business_name FROM reviews r "
                f"JOIN businesses b ON r.business_id = b.id "
                f"WHERE r.business_id={PH} ORDER BY r.sent_at DESC", (business_id,)
            )
        else:
            cur.execute(
                "SELECT r.*, b.name as business_name FROM reviews r "
                "JOIN businesses b ON r.business_id = b.id "
                "ORDER BY r.sent_at DESC"
            )
        return _rows(cur)

def get_pending_followups(days, follow_up_sent, db=None):
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(
            f"SELECT r.*, b.name as business_name, b.owner_phone, b.google_place_id "
            f"FROM reviews r JOIN businesses b ON r.business_id = b.id "
            f"WHERE r.status='sent' AND r.sent_at <= {PH} AND r.follow_up_sent={PH}",
            (cutoff, follow_up_sent)
        )
        return _rows(cur)


if __name__ == "__main__":
    import tempfile, os as _os
    tmp = tempfile.mktemp(suffix=".db")
    try:
        init(tmp)
        add_business("Cafe Blue", "+919999999991", "ChIJtest1", tmp)
        biz = get_business_by_slug("cafe-blue", tmp)
        assert biz and biz["slug"] == "cafe-blue"
        r1 = insert(biz["id"], "Rahul", "+911111111111", "Visit", tmp)
        update_status(r1, "sent", "SIDtest", tmp)
        log_reply(r1, "Great service!", "positive", tmp)
        rows = all_rows(db=tmp)
        assert rows[0]["status"] == "positive"
        assert rows[0]["reply_text"] == "Great service!"
        print(f"OK — slug: {biz['slug']}, status: {rows[0]['status']}, reply: {rows[0]['reply_text']}")
    finally:
        _os.unlink(tmp)

# ── Business lifecycle ────────────────────────────────────────────────────────

def request_deactivation(business_id, db=None):
    """Start 15-day grace period before deactivating."""
    from datetime import datetime, timedelta
    deactivate_at = (datetime.utcnow() + timedelta(days=15)).isoformat()
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(
            f"UPDATE businesses SET status='deactivating', deactivate_at={PH} WHERE id={PH}",
            (deactivate_at, business_id)
        )

def cancel_deactivation(business_id, db=None):
    """Cancel a pending deactivation — business stays active."""
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(
            f"UPDATE businesses SET status='active', deactivate_at=NULL WHERE id={PH}",
            (business_id,)
        )

def process_deactivations(db=None):
    """Called by scheduler daily — deactivates businesses past their grace period."""
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    with conn(db) as c:
        cur = _cur(c)
        cur.execute(
            f"UPDATE businesses SET active=0, status='inactive' "
            f"WHERE status='deactivating' AND deactivate_at <= {PH}",
            (now,)
        )
        count = cur.rowcount
    if count:
        print(f"[db] deactivated {count} business(es)")
    return count