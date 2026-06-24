from fastapi import FastAPI, Form, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from dotenv import load_dotenv
from html import escape
from itsdangerous import URLSafeTimedSerializer, BadSignature
import re, os
import db, whatsapp, webhook, scheduler

load_dotenv()

app = FastAPI(docs_url=None, redoc_url=None)
app.include_router(webhook.router)

HERE = Path(__file__).parent
PHONE_RE = re.compile(r"^\+\d{10,15}$")

# ── Session helpers ───────────────────────────────────────────────────────────

def _signer():
    secret = os.getenv("SECRET_KEY", "dev-secret-change-in-prod")
    return URLSafeTimedSerializer(secret)

def set_session(response, username: str):
    token = _signer().dumps(username)
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60*60*8)

def get_session(request: Request) -> str | None:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return _signer().loads(token, max_age=60*60*8)
    except BadSignature:
        return None

def require_auth(request: Request):
    if not get_session(request):
        raise HTTPException(status_code=302, headers={"Location": "/login"})

# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    required = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM", "OPENAI_API_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {missing}")
    db.init()
    scheduler.start()

# ── Render helper ─────────────────────────────────────────────────────────────

def render(filename, **kw):
    html = (HERE / "templates" / filename).read_text(encoding="utf-8")
    for k, v in kw.items():
        html = html.replace(f"{{{{ {k} }}}}", str(v))
    return html

def e(val):
    return escape(str(val)) if val is not None else ""

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

# ── Trigger form ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def trigger_form(request: Request, _=Depends(require_auth)):
    businesses = db.get_businesses()
    options = "".join(f'<option value="{e(b["id"])}">{e(b["name"])}</option>' for b in businesses)
    if not options:
        options = '<option disabled>No businesses yet — add one first</option>'
    return render("trigger.html", business_options=options)

@app.post("/submit")
def submit(
    request: Request,
    business_id:    int = Form(...),
    customer_name:  str = Form(...),
    customer_phone: str = Form(...),
    job_type:       str = Form(...),
    _=Depends(require_auth),
):
    if not PHONE_RE.match(customer_phone):
        raise HTTPException(status_code=400, detail="Invalid phone. Use format: +919876543210")
    biz = db.get_business(business_id)
    if not biz:
        raise HTTPException(status_code=400, detail="Business not found")
    row_id = db.insert(business_id, customer_name, customer_phone, job_type)
    try:
        sid = whatsapp.send_review_request(
            customer_name, customer_phone,
            biz["name"], job_type, biz["google_place_id"]
        )
        db.update_status(row_id, "sent", whatsapp_sid=sid)
    except Exception as ex:
        db.update_status(row_id, "send_failed")
        print(f"[submit] WhatsApp error: {ex}")
    return RedirectResponse(url="/dashboard", status_code=303)

# ── Businesses ────────────────────────────────────────────────────────────────

@app.get("/businesses", response_class=HTMLResponse)
def businesses_page(request: Request, _=Depends(require_auth)):
    rows = db.get_businesses()
    rows_html = "".join(
        f"<tr><td>{e(b['id'])}</td>"
        f"<td class='biz-name'>{e(b['name'])}</td>"
        f"<td>{e(b['owner_phone'])}</td>"
        f"<td><span class='place-id'>{e(b['google_place_id'])}</span></td>"
        f"<td>{e(b['created_at'][:10])}</td></tr>"
        for b in rows
    ) or "<tr><td colspan='5' class='empty'>No businesses yet. Add your first client →</td></tr>"
    return render("businesses.html", rows=rows_html)

@app.post("/businesses/add")
def add_business(
    request: Request,
    name:            str = Form(...),
    owner_phone:     str = Form(...),
    google_place_id: str = Form(...),
    _=Depends(require_auth),
):
    if not PHONE_RE.match(owner_phone):
        raise HTTPException(status_code=400, detail="Invalid phone. Use format: +919876543210")
    db.add_business(name, owner_phone, google_place_id)
    return RedirectResponse(url="/businesses", status_code=303)

# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, business_id: int = None, _=Depends(require_auth)):
    businesses = db.get_businesses()
    rows = db.all_rows(business_id=business_id)

    total     = len(rows)
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
        f"<td><span class='badge {e(r['status'])}'><span class='badge-dot'></span>{e(r['status']).replace('_',' ')}</span></td>"
        f"<td>{e(r['sent_at'][:16])}</td>"
        f"</tr>"
        for r in rows
    ) or "<tr><td colspan='6' class='empty'>No review requests yet. <a href='/'>Log your first job →</a></td></tr>"

    return render("dashboard.html",
        filter_options=filter_options,
        rows=rows_html,
        stat_total=total,
        stat_positive=positive,
        stat_complaint=complaint,
        stat_pending=pending,
    )
