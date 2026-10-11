"""
app.py - Main FastAPI Application for Face Recognition & Continuous Attendance Kiosk System.
Separates Admin Registration Portal and Attendance Collection Kiosk with distinct logins.
"""
from __future__ import annotations

import csv
import io
import os
from typing import Optional, List
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

import database as db
import ai_service as ai

# Initialize FastAPI App
app = FastAPI(title="Biometric AI Attendance & Security System", version="2.0.0")

# Session Middleware for cookie-based authentication
app.add_middleware(SessionMiddleware, secret_key="biometric_secret_super_key_2026", max_age=86400 * 7)

# Mount static and upload directories
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
os.makedirs("static/sounds", exist_ok=True)
os.makedirs("uploads/avatars", exist_ok=True)
os.makedirs("uploads/verifications", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

templates = Jinja2Templates(directory="templates")


# -----------------------------------------------------------------------------
# Dependency Helpers
# -----------------------------------------------------------------------------
def get_current_admin(request: Request) -> Optional[dict]:
    admin_data = request.session.get("admin")
    return admin_data


def get_current_kiosk(request: Request) -> Optional[dict]:
    kiosk_data = request.session.get("kiosk")
    return kiosk_data


def require_admin(request: Request):
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/admin/login"}
        )
    return admin


def require_kiosk(request: Request):
    kiosk = get_current_kiosk(request)
    if not kiosk:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/kiosk/login"}
        )
    return kiosk


# -----------------------------------------------------------------------------
# Web Page Routes
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root_index(request: Request):
    return templates.TemplateResponse(request, "portal_select.html")


# --- Admin Portal Routes ---
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if get_current_admin(request):
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    return templates.TemplateResponse(request, "admin_login.html", context={"error": None})


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request):
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=302)
    stats = db.get_dashboard_stats()
    users = db.get_all_users()
    settings = db.get_settings()
    return templates.TemplateResponse(request, "admin_dashboard.html", context={
        "admin": admin,
        "stats": stats,
        "users": users,
        "settings": settings
    })


@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.pop("admin", None)
    return RedirectResponse(url="/admin/login", status_code=302)


# --- Kiosk Portal Routes ---
@app.get("/kiosk/login", response_class=HTMLResponse)
async def kiosk_login_page(request: Request):
    if get_current_kiosk(request):
        return RedirectResponse(url="/kiosk/scanner", status_code=302)
    return templates.TemplateResponse(request, "kiosk_login.html", context={"error": None})


@app.get("/kiosk", response_class=HTMLResponse)
@app.get("/kiosk/scanner", response_class=HTMLResponse)
async def kiosk_scanner_page(request: Request):
    kiosk = get_current_kiosk(request)
    if not kiosk:
        return RedirectResponse(url="/kiosk/login", status_code=302)
    return templates.TemplateResponse(request, "kiosk_scanner.html", context={
        "kiosk": kiosk
    })


@app.get("/kiosk/logout")
async def kiosk_logout(request: Request):
    request.session.pop("kiosk", None)
    return RedirectResponse(url="/kiosk/login", status_code=302)


# -----------------------------------------------------------------------------
# Authentication API
# -----------------------------------------------------------------------------
class AdminLoginReq(BaseModel):
    username: str
    password: str


@app.post("/api/admin/login")
async def api_admin_login(request: Request, payload: AdminLoginReq):
    admin = db.verify_admin(payload.username, payload.password)
    if not admin:
        return JSONResponse({"success": False, "message": "Invalid Administrator credentials"}, status_code=401)
    request.session["admin"] = {"id": admin["id"], "username": admin["username"], "name": admin["full_name"]}
    return {"success": True, "redirect": "/admin/dashboard"}


class KioskLoginReq(BaseModel):
    pin_code: str


@app.post("/api/kiosk/login")
async def api_kiosk_login(request: Request, payload: KioskLoginReq):
    kiosk = db.verify_kiosk(payload.pin_code)
    if not kiosk:
        return JSONResponse({"success": False, "message": "Invalid Kiosk Access PIN"}, status_code=401)
    request.session["kiosk"] = {"id": kiosk["id"], "name": kiosk["device_name"], "location": kiosk["location"]}
    return {"success": True, "redirect": "/kiosk/scanner"}


# -----------------------------------------------------------------------------
# Admin APIs: User Management & Enrollment
# -----------------------------------------------------------------------------
class EnrollRequest(BaseModel):
    employee_id: str
    name: str
    department: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    frames: List[str]


@app.post("/api/admin/enroll")
async def api_enroll_user(request: Request, payload: EnrollRequest):
    admin = get_current_admin(request)
    if not admin:
        return JSONResponse({"success": False, "message": "Unauthorized Admin"}, status_code=401)

    result = ai.enroll_user_embeddings(
        employee_id=payload.employee_id.strip(),
        name=payload.name.strip(),
        department=payload.department.strip(),
        email=payload.email.strip() if payload.email else "",
        phone=payload.phone.strip() if payload.phone else "",
        frames_b64=payload.frames
    )
    return result


@app.get("/api/admin/users")
async def api_get_users(request: Request):
    if not get_current_admin(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    return {"success": True, "users": db.get_all_users()}


@app.delete("/api/admin/users/{employee_id}")
async def api_delete_user(request: Request, employee_id: str):
    if not get_current_admin(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    user = db.get_user_by_emp_id(employee_id)
    if not user:
        return JSONResponse({"success": False, "message": "User not found"}, status_code=404)

    # Remove from gallery and SQLite
    _, _, gallery, cfg = ai.get_ai_components()
    gallery.remove(user["name"])
    gallery.save()
    db.delete_user(employee_id)

    return {"success": True, "message": f"User {user['name']} ({employee_id}) removed from system."}


@app.get("/api/admin/stats")
async def api_get_stats(request: Request):
    if not get_current_admin(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    return {"success": True, "stats": db.get_dashboard_stats()}


@app.get("/api/admin/attendance")
async def api_get_attendance(request: Request, limit: int = 200):
    if not get_current_admin(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    logs = db.get_all_attendance_logs(limit=limit)
    return {"success": True, "logs": logs}


@app.get("/api/admin/export-attendance")
async def api_export_attendance(request: Request):
    if not get_current_admin(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    logs = db.get_all_attendance_logs(limit=2000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Log ID", "Employee ID", "Full Name", "Department", "Date", "Time", "Status", "Similarity Match", "PAD Liveness Score", "Device"])

    for row in logs:
        writer.writerow([
            row["id"], row["employee_id"], row["user_name"], row["department"],
            row["date_str"], row["time_str"], row["status"],
            f"{row['similarity_score']:.3f}", f"{row['anti_spoof_score']:.3f}", row["device_name"]
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendance_report.csv"}
    )


class SettingsUpdateReq(BaseModel):
    match_thresh: str
    margin: str
    live_score_thresh: str
    cooldown_minutes: str
    late_cutoff_time: str


@app.post("/api/admin/settings")
async def api_save_settings(request: Request, payload: SettingsUpdateReq):
    if not get_current_admin(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    db.update_settings(payload.dict())
    ai.reload_settings()
    return {"success": True, "message": "Settings updated successfully"}


# -----------------------------------------------------------------------------
# Kiosk Real-Time APIs: Continuous Frame Processing & Verification
# -----------------------------------------------------------------------------
class KioskFrameReq(BaseModel):
    frame: str
    challenge: Optional[str] = None


@app.post("/api/kiosk/process-frame")
async def api_kiosk_process_frame(payload: KioskFrameReq):
    frame = ai.decode_image_base64(payload.frame)
    if frame is None:
        return {"has_face": False, "reason": "invalid frame"}

    analysis = ai.process_kiosk_frame(frame, payload.challenge)
    return analysis


class KioskVerifyReq(BaseModel):
    frames: List[str]
    device_name: Optional[str] = "Main Kiosk"


@app.post("/api/kiosk/verify")
async def api_kiosk_verify(payload: KioskVerifyReq):
    res = ai.complete_kiosk_verification(payload.frames, device_name=payload.device_name or "Main Kiosk")
    return res


@app.get("/api/kiosk/today-logs")
async def api_kiosk_today_logs():
    logs = db.get_today_attendance()
    return {"success": True, "logs": logs}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
