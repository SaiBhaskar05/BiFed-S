"""
database.py - SQLite Database persistence layer for Face Recognition Attendance System.
Handles users, attendance records, kiosk devices, admin credentials, and system settings.
"""
from __future__ import annotations

import os
import sqlite3
import hashlib
from datetime import datetime, date
from typing import List, Dict, Optional, Any

DB_FILE = "attendance_system.db"


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_db():
    os.makedirs("uploads/avatars", exist_ok=True)
    os.makedirs("uploads/verifications", exist_ok=True)

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Admin table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Kiosk login devices
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kiosks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_name TEXT UNIQUE NOT NULL,
                pin_code TEXT NOT NULL,
                location TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                last_active DATETIME
            )
        """)

        # Registered Users
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                department TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                avatar_path TEXT,
                sample_count INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Attendance Logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT NOT NULL,
                employee_id TEXT NOT NULL,
                department TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                date_str TEXT NOT NULL,
                time_str TEXT NOT NULL,
                status TEXT NOT NULL,
                similarity_score REAL NOT NULL,
                anti_spoof_score REAL NOT NULL,
                device_name TEXT DEFAULT 'Main Kiosk',
                snapshot_path TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)

        # Settings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Seed default Admin if not exists (username: admin, password: admin123)
        cursor.execute("SELECT id FROM admins WHERE username = 'admin'")
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO admins (username, password_hash, full_name)
                VALUES ('admin', ?, 'System Administrator')
            """, (hash_password("admin123"),))

        # Seed default Kiosk if not exists (device_name: Main Kiosk, pin: 1234)
        cursor.execute("SELECT id FROM kiosks WHERE device_name = 'Main Entrance Kiosk'")
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO kiosks (device_name, pin_code, location)
                VALUES ('Main Entrance Kiosk', '1234', 'Front Entrance Gate')
            """)

        # Seed default Settings
        default_settings = {
            "match_thresh": "0.45",
            "margin": "0.08",
            "live_score_thresh": "0.68",
            "cooldown_minutes": "5",
            "late_cutoff_time": "09:30",
            "voice_enabled": "true"
        }
        for k, v in default_settings.items():
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        conn.commit()


# -----------------------------------------------------------------------------
# Admin & Kiosk Auth
# -----------------------------------------------------------------------------
def verify_admin(username: str, password: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admins WHERE username = ?", (username,))
        row = cursor.fetchone()
        if row and row["password_hash"] == hash_password(password):
            return dict(row)
    return None


def verify_kiosk(pin_code: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kiosks WHERE pin_code = ? AND is_active = 1", (pin_code,))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE kiosks SET last_active = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
            conn.commit()
            return dict(row)
    return None


# -----------------------------------------------------------------------------
# User Management
# -----------------------------------------------------------------------------
def get_all_users() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_user_by_name(name: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE name = ?", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_emp_id(emp_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE employee_id = ?", (emp_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def create_or_update_user(employee_id: str, name: str, department: str, email: str = "", phone: str = "", avatar_path: str = "", sample_count: int = 1) -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE employee_id = ?", (employee_id,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
                UPDATE users
                SET name = ?, department = ?, email = ?, phone = ?, avatar_path = COALESCE(NULLIF(?, ''), avatar_path),
                    sample_count = ?, updated_at = CURRENT_TIMESTAMP
                WHERE employee_id = ?
            """, (name, department, email, phone, avatar_path, sample_count, employee_id))
            user_id = existing["id"]
        else:
            cursor.execute("""
                INSERT INTO users (employee_id, name, department, email, phone, avatar_path, sample_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (employee_id, name, department, email, phone, avatar_path, sample_count))
            user_id = cursor.lastrowid
        conn.commit()
        return user_id


def delete_user(employee_id_or_name: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE employee_id = ? OR name = ?", (employee_id_or_name, employee_id_or_name))
        conn.commit()
        return cursor.rowcount > 0


# -----------------------------------------------------------------------------
# Attendance Logs
# -----------------------------------------------------------------------------
def log_attendance(name: str, similarity: float, anti_spoof: float, device_name: str = "Main Kiosk", snapshot_path: str = "") -> Dict[str, Any]:
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%I:%M:%S %p")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        user = get_user_by_name(name)
        user_id = user["id"] if user else None
        emp_id = user["employee_id"] if user else "UNKNOWN"
        dept = user["department"] if user else "General"

        # Check late cutoff from settings
        cursor.execute("SELECT value FROM settings WHERE key = 'late_cutoff_time'")
        late_cutoff = cursor.fetchone()
        cutoff_val = late_cutoff["value"] if late_cutoff else "09:30"
        try:
            cutoff_time = datetime.strptime(cutoff_val, "%H:%M").time()
            status = "Late" if now.time() > cutoff_time else "Present"
        except Exception:
            status = "Present"

        cursor.execute("""
            INSERT INTO attendance_logs (
                user_id, user_name, employee_id, department, timestamp,
                date_str, time_str, status, similarity_score, anti_spoof_score,
                device_name, snapshot_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, name, emp_id, dept, now.strftime("%Y-%m-%d %H:%M:%S"),
              date_str, time_str, status, similarity, anti_spoof, device_name, snapshot_path))
        conn.commit()
        log_id = cursor.lastrowid

        return {
            "id": log_id,
            "user_name": name,
            "employee_id": emp_id,
            "department": dept,
            "date": date_str,
            "time": time_str,
            "status": status,
            "similarity": similarity,
            "anti_spoof": anti_spoof,
            "avatar": user["avatar_path"] if user else None
        }


def get_today_attendance() -> List[Dict[str, Any]]:
    today_str = date.today().strftime("%Y-%m-%d")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, u.avatar_path
            FROM attendance_logs a
            LEFT JOIN users u ON a.user_id = u.id
            WHERE a.date_str = ?
            ORDER BY a.timestamp DESC
        """, (today_str,))
        return [dict(row) for row in cursor.fetchall()]


def get_all_attendance_logs(limit: int = 500) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, u.avatar_path
            FROM attendance_logs a
            LEFT JOIN users u ON a.user_id = u.id
            ORDER BY a.timestamp DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_last_checkin_seconds_ago(name: str) -> Optional[float]:
    today_str = date.today().strftime("%Y-%m-%d")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp FROM attendance_logs
            WHERE user_name = ? AND date_str = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (name, today_str))
        row = cursor.fetchone()
        if row:
            last_time = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            return (datetime.now() - last_time).total_seconds()
    return None


def get_dashboard_stats() -> Dict[str, Any]:
    today_str = date.today().strftime("%Y-%m-%d")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_active = 1")
        total_users = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(DISTINCT user_name) as count FROM attendance_logs WHERE date_str = ?", (today_str,))
        today_present = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM attendance_logs WHERE date_str = ? AND status = 'Late'", (today_str,))
        today_late = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM attendance_logs")
        total_logs = cursor.fetchone()["count"]

        return {
            "total_users": total_users,
            "today_present": today_present,
            "today_absent": max(0, total_users - today_present),
            "today_late": today_late,
            "attendance_rate": f"{(today_present / total_users * 100):.1f}%" if total_users > 0 else "0%",
            "total_logs": total_logs
        }


# -----------------------------------------------------------------------------
# Settings Access
# -----------------------------------------------------------------------------
def get_settings() -> Dict[str, str]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in cursor.fetchall()}


def update_settings(settings_dict: Dict[str, str]):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for k, v in settings_dict.items():
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
        conn.commit()


# Initialize database on module load
init_db()
