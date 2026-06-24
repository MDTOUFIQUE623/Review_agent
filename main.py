from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from dotenv import load_dotenv
import db
import whatsapp
import webhook
import scheduler

load_dotenv()

app = FastAPI()
app.include_router(webhook.router)

HERE = Path(__file__).parent

def render(filename, **kw):
    html = (HERE / "templates" / filename).read_text(encoding="utf-8")
    for k, v in kw.items():
        html = html.replace(f"{{{{ {k} }}}}", v)
    return html

@app.on_event("startup")
def startup():
    db.init()
    scheduler.start()

# ── Trigger form ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def trigger_form():
    businesses = db.get_businesses()
    options = "".join(f'<option value="{b["id"]}">{b["name"]}</option>' for b in businesses)
    if not options:
        options = '<option disabled>No businesses yet — add one below</option>'
    return render("trigger.html", business_options=options)

@app.post("/submit")
def submit(
    business_id:    int = Form(...),
    customer_name:  str = Form(...),
    customer_phone: str = Form(...),
    job_type:       str = Form(...),
):
    biz = db.get_business(business_id)
    row_id = db.insert(business_id, customer_name, customer_phone, job_type)
    try:
        sid = whatsapp.send_review_request(
            customer_name, customer_phone,
            biz["name"], job_type, biz["google_place_id"]
        )
        db.update_status(row_id, "sent", whatsapp_sid=sid)
    except Exception as e:
        db.update_status(row_id, "send_failed")
        print(f"[submit] WhatsApp error: {e}")
    return RedirectResponse(url="/dashboard", status_code=303)

# ── Business management ───────────────────────────────────────────────────────

@app.get("/businesses", response_class=HTMLResponse)
def businesses_page():
    rows = db.get_businesses()
    rows_html = "".join(
        f"<tr><td>{b['id']}</td><td>{b['name']}</td><td>{b['owner_phone']}</td>"
        f"<td>{b['google_place_id']}</td><td>{b['created_at']}</td></tr>"
        for b in rows
    )
    return render("businesses.html", rows=rows_html)

@app.post("/businesses/add")
def add_business(
    name:            str = Form(...),
    owner_phone:     str = Form(...),
    google_place_id: str = Form(...),
):
    db.add_business(name, owner_phone, google_place_id)
    return RedirectResponse(url="/businesses", status_code=303)

# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(business_id: int = None):
    businesses = db.get_businesses()
    rows = db.all_rows(business_id=business_id)

    filter_options = '<option value="">All Businesses</option>' + "".join(
        f'<option value="{b["id"]}" {"selected" if b["id"]==business_id else ""}>{b["name"]}</option>'
        for b in businesses
    )
    rows_html = "".join(
        f"<tr><td>{r['id']}</td><td>{r['business_name']}</td><td>{r['customer_name']}</td>"
        f"<td>{r['customer_phone']}</td><td>{r['job_type']}</td>"
        f"<td><span class='status {r['status']}'>{r['status']}</span></td>"
        f"<td>{r['sent_at']}</td></tr>"
        for r in rows
    )
    return render("dashboard.html", filter_options=filter_options, rows=rows_html)