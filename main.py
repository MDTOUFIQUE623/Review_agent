from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from dotenv import load_dotenv
import db
import whatsapp

load_dotenv()

app = FastAPI()

HERE = Path(__file__).parent

def render(filename: str, **replacements) -> str:
    html = (HERE / "templates" / filename).read_text(encoding="utf-8")
    for key, val in replacements.items():
        html = html.replace(f"{{{{ {key} }}}}", val)
    return html

@app.on_event("startup")
def startup():
    db.init()

# ── Trigger form ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def trigger_form():
    return render("trigger.html")

@app.post("/submit")
def submit(
    customer_name:  str = Form(...),
    customer_phone: str = Form(...),
    business_name:  str = Form(...),
    job_type:       str = Form(...),
):
    row_id = db.insert(customer_name, customer_phone, business_name, job_type)
    try:
        sid = whatsapp.send_review_request(customer_name, customer_phone, business_name, job_type)
        db.update_status(row_id, "sent", whatsapp_sid=sid)
    except Exception as e:
        db.update_status(row_id, "send_failed")
        print(f"WhatsApp error: {e}")  # visible in uvicorn logs
    return RedirectResponse(url=f"/dashboard?new={row_id}", status_code=303)

# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    rows = db.all_rows()
    rows_html = "".join(
        f"<tr><td>{r['id']}</td><td>{r['customer_name']}</td><td>{r['customer_phone']}</td>"
        f"<td>{r['business_name']}</td><td>{r['job_type']}</td>"
        f"<td><span class='status {r['status']}'>{r['status']}</span></td>"
        f"<td>{r['sent_at']}</td></tr>"
        for r in rows
    )
    return render("dashboard.html", rows=rows_html)