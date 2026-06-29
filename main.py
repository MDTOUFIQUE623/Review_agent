from fastapi import FastAPI, Form, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path
from dotenv import load_dotenv
from html import escape
from itsdangerous import URLSafeTimedSerializer, BadSignature
import re, os, io
import db, whatsapp, webhook, scheduler
import redis, phonenumbers, httpx

load_dotenv()

app = FastAPI(docs_url=None, redoc_url=None)
app.include_router(webhook.router)

HERE = Path(__file__).parent
PHONE_RE = re.compile(r"^\+\d{10,15}$")

# ── Redis Rate Limiter ────────────────────────────────────────────────────────

# ponytail: redis rate limiting client
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)

from collections import defaultdict
import time

_local_limiter = defaultdict(list)

# ── Session & CSRF ────────────────────────────────────────────────────────────

def _signer():
    key = os.getenv("SECRET_KEY")
    if not key:
        raise RuntimeError("SECRET_KEY environment variable is not set.")
    return URLSafeTimedSerializer(key)

def set_session(response, username):
    import secrets
    csrf_token = secrets.token_hex(32)
    session_data = {"username": username, "csrf_token": csrf_token}
    token = _signer().dumps(session_data)
    secure = os.getenv("BASE_URL", "").startswith("https")
    response.set_cookie("session", token, httponly=True, samesite="lax", secure=secure, max_age=60*60*8)

def get_session(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        data = _signer().loads(token, max_age=60*60*8)
        return data if isinstance(data, dict) else {"username": data}
    except BadSignature:
        return None

def require_auth(request: Request):
    if not get_session(request):
        raise HTTPException(status_code=302, headers={"Location": "/login"})

async def verify_csrf(request: Request):
    if request.method == "POST":
        session_data = get_session(request)
        if not session_data or "csrf_token" not in session_data:
            raise HTTPException(status_code=403, detail="CSRF token missing from session")
        form_data = await request.form()
        form_token = form_data.get("csrf_token")
        if not form_token or form_token != session_data["csrf_token"]:
            raise HTTPException(status_code=403, detail="CSRF token invalid or missing")

# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    db.init()
    
    # Core required vars
    required = ["OPENAI_API_KEY", "SECRET_KEY"]
    
    # Provider-aware dynamic required checks
    try:
        active_providers = db.get_active_providers()
    except Exception:
        active_providers = []
        
    if "twilio" in active_providers:
        required.extend(["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM"])
    if "meta" in active_providers:
        required.extend(["META_ACCESS_TOKEN", "META_PHONE_NUMBER_ID"])
    if "interakt" in active_providers:
        required.extend(["INTERAKT_API_KEY"])
        
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars for active providers: {missing}")
        
    scheduler.start()

# ── Helpers ───────────────────────────────────────────────────────────────────

def render(filename, **kw):
    html = (HERE / "templates" / filename).read_text(encoding="utf-8")
    for k, v in kw.items():
        html = html.replace(f"{{{{ {k} }}}}", str(v))
    return html

def e(val):
    return escape(str(val)) if val is not None else ""

from datetime import datetime

def fmt_datetime(value):
    if value is None:
        return ""

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")

    return str(value)[:16]

def check_rate_limit(ip: str) -> bool:
    key = f"rate:{ip}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, 60)
        return count <= 2
    except Exception as ex:
        # ponytail: fallback to local memory rate limiter if Redis is offline
        print(f"[limiter] Redis connection error: {ex}, falling back to local memory")
        now = time.time()
        _local_limiter[ip] = [t for t in _local_limiter[ip] if now - t < 60]
        if len(_local_limiter[ip]) >= 2:
            return False
        _local_limiter[ip].append(now)
        return True

def sanitize_input(text: str) -> str:
    # ponytail: simple regex tag stripper to sanitize input and avoid markup dependencies
    text = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]*>", "", text).strip()

def is_valid_phone(phone: str) -> bool:
    try:
        parsed = phonenumbers.parse(phone)
        if not phone.startswith("+"):
            return False
        return phonenumbers.is_valid_number(parsed)
    except Exception:
        return False

# ── Login / Logout ────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_session(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return render("login.html", error_display="none", error_msg="")

@app.post("/login", response_class=HTMLResponse)
def login_submit(username: str = Form(...), password: str = Form(...)):
    import secrets as sec
    valid_user = sec.compare_digest(username, os.getenv("ADMIN_USER", "admin"))
    valid_pass = sec.compare_digest(password, os.getenv("ADMIN_PASS", "changeme"))
    if not (valid_user and valid_pass):
        return render("login.html", error_display="block", error_msg="Incorrect username or password.")
    response = RedirectResponse(url="/dashboard", status_code=303)
    set_session(response, username)
    return response

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session")
    return response

# ── Public QR landing page ────────────────────────────────────────────────────

@app.get("/r/{slug}", response_class=HTMLResponse)
def qr_landing(slug: str):
    biz = db.get_business_by_slug(slug)
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    return render("landing.html", business_name=e(biz["name"]), slug=e(slug))

@app.post("/r/{slug}/submit")
async def qr_submit(request: Request, slug: str, customer_name: str = Form(...), customer_phone: str = Form(...)):
    # ponytail: check rate limit first to avoid DB / api overhead
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host
    if not check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")

    biz = db.get_business_by_slug(slug)
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")

    customer_name = sanitize_input(customer_name)
    customer_phone = customer_phone.strip()

    if not is_valid_phone(customer_phone):
        raise HTTPException(status_code=400, detail="Invalid phone number format.")

    row_id = db.insert(biz["id"], customer_name, customer_phone, "Visit")
    try:
        sid = whatsapp.send_review_request(
            customer_name, customer_phone,
            biz["name"], "visit", biz["google_place_id"],
            biz
        )
        db.update_status(row_id, "sent", whatsapp_sid=sid)
    except httpx.HTTPError as ex:
        db.update_status(row_id, "send_failed", whatsapp_sid=f"HTTP Error: {ex}")
        print(f"[qr_submit] HTTP error: {ex}")
    except ValueError as ex:
        db.update_status(row_id, "send_failed", whatsapp_sid=f"Value Error: {ex}")
        print(f"[qr_submit] Value error: {ex}")
    except Exception as ex:
        db.update_status(row_id, "send_failed", whatsapp_sid=f"Error: {ex}")
        print(f"[qr_submit] General error: {ex}")
    return JSONResponse({"ok": True})

# ── QR code image download ────────────────────────────────────────────────────

@app.get("/businesses/{business_id}/qr")
def download_qr(business_id: int, _=Depends(require_auth)):
    import qrcode
    biz = db.get_business(business_id)
    if not biz:
        raise HTTPException(status_code=404)
    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    url = f"{base_url}/r/{biz['slug']}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    filename = f"qr-{biz['slug']}.png"
    return StreamingResponse(buf, media_type="image/png",
        headers={"Content-Disposition": f"attachment; filename={filename}"})

# ── Trigger form (manual, kept for operator use) ──────────────────────────────

@app.get("/", response_class=HTMLResponse)
def trigger_form(request: Request, _=Depends(require_auth)):
    businesses = db.get_businesses()
    options = "".join(f'<option value="{e(b["id"])}">{e(b["name"])}</option>' for b in businesses)
    if not options:
        options = '<option disabled>No businesses yet — add one first</option>'
    session_data = get_session(request)
    csrf_token = session_data.get("csrf_token") if session_data else ""
    return render("trigger.html", business_options=options, csrf_token=csrf_token)

@app.post("/submit")
async def submit(
    request: Request,
    business_id:    int = Form(...),
    customer_name:  str = Form(...),
    customer_phone: str = Form(...),
    job_type:       str = Form(...),
    _=Depends(require_auth),
    __=Depends(verify_csrf),
):
    customer_name = sanitize_input(customer_name)
    customer_phone = customer_phone.strip()
    job_type = sanitize_input(job_type)

    if not is_valid_phone(customer_phone):
        raise HTTPException(status_code=400, detail="Invalid phone. Use format: +919876543210")
    biz = db.get_business(business_id)
    if not biz:
        raise HTTPException(status_code=400, detail="Business not found")
    row_id = db.insert(business_id, customer_name, customer_phone, job_type)
    try:
        sid = whatsapp.send_review_request(
            customer_name, customer_phone,
            biz["name"], job_type, biz["google_place_id"],
            biz
        )
        db.update_status(row_id, "sent", whatsapp_sid=sid)
    except httpx.HTTPError as ex:
        db.update_status(row_id, "send_failed", whatsapp_sid=f"HTTP Error: {ex}")
        print(f"[submit] HTTP error: {ex}")
    except ValueError as ex:
        db.update_status(row_id, "send_failed", whatsapp_sid=f"Value Error: {ex}")
        print(f"[submit] Value error: {ex}")
    except Exception as ex:
        db.update_status(row_id, "send_failed", whatsapp_sid=f"Error: {ex}")
        print(f"[submit] General error: {ex}")
    return RedirectResponse(url="/dashboard", status_code=303)

# ── Businesses ────────────────────────────────────────────────────────────────

@app.get("/businesses", response_class=HTMLResponse)
def businesses_page(request: Request, _=Depends(require_auth)):
    rows = db.get_businesses()
    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    session_data = get_session(request)
    csrf_token = session_data.get("csrf_token") if session_data else ""

    def _status_badge(b):
        status = b.get("status", "active")
        if status == "deactivating":
            days_left = ""
            if b.get("deactivate_at"):
                from datetime import datetime
                try:
                    delta = datetime.fromisoformat(str(b["deactivate_at"])) - datetime.utcnow()
                    days_left = f" ({max(0, delta.days)}d left)"
                except Exception:
                    pass
            return f"<span class='badge-biz deactivating'>Deactivating{days_left}</span>"
        return "<span class='badge-biz active'>Active</span>"

    def _actions(b, token):
        bid = e(b["id"])
        status = b.get("status", "active")
        qr = f"<a href='/businesses/{bid}/qr' class='btn-sm'>&#11015; QR</a>"
        csrf_input = f"<input type='hidden' name='csrf_token' value='{token}'>"
        if status == "deactivating":
            return qr + (
                f" <form method='POST' action='/businesses/{bid}/cancel-deactivation' style='display:inline'>"
                f"{csrf_input}<button class='btn-sm btn-green'>Cancel</button></form>"
            )
        return qr + (
            f" <form method='POST' action='/businesses/{bid}/deactivate' style='display:inline'>"
            f"{csrf_input}<button class='btn-sm btn-red'>Remove</button></form>"
        )

    rows_html = "".join(
        f"<tr><td>{e(b['id'])}</td>"
        f"<td class='biz-name'>{e(b['name'])}</td>"
        f"<td>{e(b['owner_phone'])}</td>"
        f"<td><code>{base_url}/r/{e(b['slug'])}</code></td>"
        f"<td>{_status_badge(b)}</td>"
        f"<td>{_actions(b, csrf_token)}</td>"
        f"<td>{e(str(b['created_at'])[:10])}</td></tr>"
        for b in rows
    ) or "<tr><td colspan='7' class='empty'>No businesses yet. Add your first client →</td></tr>"
    return render("businesses.html", rows=rows_html, csrf_token=csrf_token)

@app.post("/businesses/add")
def add_business(
    request: Request,
    name:            str = Form(...),
    owner_phone:     str = Form(...),
    google_place_id: str = Form(...),
    provider:        str = Form("twilio"),
    _=Depends(require_auth),
    __=Depends(verify_csrf),
):
    owner_phone = owner_phone.strip()
    if not is_valid_phone(owner_phone):
        raise HTTPException(status_code=400, detail="Invalid phone. Use format: +919876543210")
    db.add_business(name, owner_phone, google_place_id, provider, "{}")
    return RedirectResponse(url="/businesses", status_code=303)

# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, business_id: int = None, _=Depends(require_auth)):
    businesses = db.get_businesses()
    rows = db.all_rows(business_id=business_id)

    total     = sum(1 for r in rows if r["status"] != "send_failed")
    positive  = sum(1 for r in rows if r["status"] == "positive")
    complaint = sum(1 for r in rows if r["status"] == "complaint")
    pending   = sum(1 for r in rows if r["status"] == "sent")

    filter_options = '<option value="">All Businesses</option>' + "".join(
        f'<option value="{e(b["id"])}" {"selected" if b["id"]==business_id else ""}>{e(b["name"])}</option>'
        for b in businesses
    )

    rows_html = "".join(
        f"<tr>"
        f"<td>{e(r['id'])}</td>"
        f"<td class='customer-name'>{e(r['customer_name'])}<br><span class='phone'>{e(r['customer_phone'])}</span></td>"
        f"<td>{e(r['business_name'])}</td>"
        f"<td>{e(r['job_type'])}</td>"
        f"<td><span class='badge {e(r['status'])}' {('title=\"' + e(r['whatsapp_sid']).replace('\n', ' ') + '\"') if r['status'] == 'send_failed' and r['whatsapp_sid'] else ''}><span class='badge-dot'></span>{e(r['status']).replace('_',' ')}</span></td>"
        f"<td class='reply-cell'>{('<span class=\"reply-text\">' + e(r['reply_text']) + '</span>') if r['reply_text'] else '<span class=\"no-reply\">—</span>'}</td>"
        f"<td>{e(fmt_datetime(r['sent_at']))}</td>"
        f"</tr>"
        for r in rows
    ) or "<tr><td colspan='7' class='empty'>No review requests yet. <a href='/'>Log your first job →</a></td></tr>"

    session_data = get_session(request)
    csrf_token = session_data.get("csrf_token") if session_data else ""

    return render("dashboard.html",
        filter_options=filter_options,
        rows=rows_html,
        stat_total=total,
        stat_positive=positive,
        stat_complaint=complaint,
        stat_pending=pending,
    )

# ── Business lifecycle ────────────────────────────────────────────────────────

@app.post("/businesses/{business_id}/deactivate")
def deactivate_business(business_id: int, request: Request, _=Depends(require_auth), __=Depends(verify_csrf)):
    biz = db.get_business(business_id)
    if not biz:
        raise HTTPException(status_code=404)
    db.request_deactivation(business_id)
    return RedirectResponse(url="/businesses", status_code=303)

@app.post("/businesses/{business_id}/cancel-deactivation")
def cancel_deactivation(business_id: int, request: Request, _=Depends(require_auth), __=Depends(verify_csrf)):
    biz = db.get_business(business_id)
    if not biz:
        raise HTTPException(status_code=404)
    db.cancel_deactivation(business_id)
    return RedirectResponse(url="/businesses", status_code=303)