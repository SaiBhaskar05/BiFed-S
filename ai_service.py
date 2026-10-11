"""
ai_service.py - High-Performance Bridge between FastAPI and AI models.
Optimized for ultra-low latency continuous scanning and instantaneous verification.
"""
from __future__ import annotations

import base64
import os
import threading
import time
from typing import Dict, Any, Optional, List, Tuple
import cv2
import numpy as np

from face_system import Config, FaceEngine, SpoofDetector, Gallery, MatchResult
import database as db

_lock = threading.Lock()
_engine: Optional[FaceEngine] = None
_spoof: Optional[SpoofDetector] = None
_gallery: Optional[Gallery] = None
_cfg = Config(det_size=(320, 320))  # 320x320 for 3x faster detection


def get_ai_components() -> Tuple[FaceEngine, SpoofDetector, Gallery, Config]:
    global _engine, _spoof, _gallery, _cfg
    with _lock:
        if _engine is None:
            _cfg = Config(det_size=(320, 320))
            settings = db.get_settings()
            if "match_thresh" in settings:
                _cfg.match_thresh = float(settings["match_thresh"])
            if "margin" in settings:
                _cfg.margin = float(settings["margin"])
            if "live_score_thresh" in settings:
                _cfg.live_score_thresh = float(settings["live_score_thresh"])

            _engine = FaceEngine(_cfg)
            _spoof = SpoofDetector(_cfg)
            _gallery = Gallery(_cfg.db_path, _cfg)
    return _engine, _spoof, _gallery, _cfg


def reload_settings():
    global _cfg, _gallery
    with _lock:
        if _cfg is not None:
            settings = db.get_settings()
            if "match_thresh" in settings:
                _cfg.match_thresh = float(settings["match_thresh"])
            if "margin" in settings:
                _cfg.margin = float(settings["margin"])
            if "live_score_thresh" in settings:
                _cfg.live_score_thresh = float(settings["live_score_thresh"])
            if _gallery is not None:
                _gallery.cfg = _cfg


def decode_image_base64(data_uri_or_base64: str) -> Optional[np.ndarray]:
    try:
        if "," in data_uri_or_base64:
            data_uri_or_base64 = data_uri_or_base64.split(",", 1)[1]
        img_bytes = base64.b64decode(data_uri_or_base64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return frame
    except Exception:
        return None


def process_kiosk_frame(frame: np.ndarray, expected_challenge: Optional[str] = None) -> Dict[str, Any]:
    """
    Ultra-fast tracking analysis (runs in ~15-30ms).
    Focuses on face bounding box, pose, and quality without heavy spoof/gallery overhead.
    """
    engine, _, _, _ = get_ai_components()
    H, W = frame.shape[:2]

    with _lock:
        obs = engine.analyze(frame)

    if obs.face is None:
        return {
            "has_face": False,
            "reason": obs.reason,
            "usable": False,
            "box": None,
            "turn_ratio": 0.0,
            "is_frontal": False
        }

    f = obs.face
    x1, y1, x2, y2 = [int(v) for v in f.bbox]
    box = {
        "x": max(0, x1),
        "y": max(0, y1),
        "w": min(W, x2) - max(0, x1),
        "h": min(H, y2) - max(0, y1)
    }

    return {
        "has_face": True,
        "reason": obs.reason,
        "usable": obs.usable,
        "is_frontal": obs.frontal,
        "turn_ratio": round(float(obs.turn_ratio), 3),
        "box": box
    }


def complete_kiosk_verification(frames_b64: List[str], device_name: str = "Main Kiosk") -> Dict[str, Any]:
    """
    Fast, highly optimized instantaneous verification.
    Evaluates anti-spoofing and ArcFace match with minimal latency (<150ms).
    """
    engine, spoof, gallery, cfg = get_ai_components()
    settings = db.get_settings()
    cooldown_sec = float(settings.get("cooldown_minutes", "5")) * 60.0

    if not frames_b64:
        return {"success": False, "message": "No frame captured"}

    best_obs = None
    best_frame = None

    with _lock:
        # Evaluate provided frame(s)
        for b64 in frames_b64[-2:]:  # Take the freshest 1-2 frames
            frame = decode_image_base64(b64)
            if frame is None:
                continue
            obs = engine.analyze(frame)
            if obs.face is not None and obs.usable and obs.frontal:
                best_obs = obs
                best_frame = frame
                break

        if best_obs is None or best_obs.face is None:
            return {"success": False, "message": "Please look directly at camera and hold steady."}

        f = best_obs.face
        # Fast PAD MiniFASNet Score
        spoof_score = float(spoof.score(best_frame, f.bbox))

        if spoof_score < cfg.live_score_thresh:
            return {
                "success": False,
                "is_spoof": True,
                "anti_spoof_score": round(spoof_score, 3),
                "message": f"Spoof Detected! (PAD: {(spoof_score*100):.1f}%)"
            }

        # Fast 1:N Gallery Identification
        m = gallery.identify(f.normed_embedding)

    if not m.accepted or m.name == "Unknown":
        return {
            "success": False,
            "message": f"Access Denied ({m.reason})",
            "score": round(m.score, 3),
            "anti_spoof_score": round(spoof_score, 3)
        }

    # Check Cooldown to avoid duplicate check-ins
    last_seen_sec = db.get_last_checkin_seconds_ago(m.name)
    if last_seen_sec is not None and last_seen_sec < cooldown_sec:
        remaining_mins = max(1, int((cooldown_sec - last_seen_sec) / 60))
        user = db.get_user_by_name(m.name)
        return {
            "success": True,
            "already_marked": True,
            "name": m.name,
            "employee_id": user["employee_id"] if user else "",
            "department": user["department"] if user else "",
            "avatar": user["avatar_path"] if user else None,
            "message": f"Already checked in! Cooldown: {remaining_mins}m left",
            "score": round(m.score, 3),
            "anti_spoof_score": round(spoof_score, 3)
        }

    # Save snapshot
    snap_path = ""
    if best_frame is not None:
        snap_filename = f"uploads/verifications/{m.name}_{int(time.time())}.jpg"
        cv2.imwrite(snap_filename, best_frame)
        snap_path = f"/{snap_filename}"

    # Log Attendance Record in SQLite
    log_entry = db.log_attendance(
        name=m.name,
        similarity=round(m.score, 3),
        anti_spoof=round(spoof_score, 3),
        device_name=device_name,
        snapshot_path=snap_path
    )

    return {
        "success": True,
        "already_marked": False,
        "name": m.name,
        "employee_id": log_entry["employee_id"],
        "department": log_entry["department"],
        "avatar": log_entry["avatar"],
        "time": log_entry["time"],
        "date": log_entry["date"],
        "status": log_entry["status"],
        "score": round(m.score, 3),
        "anti_spoof_score": round(spoof_score, 3),
        "message": f"Welcome {m.name}! Marked as {log_entry['status']}"
    }


def enroll_user_embeddings(employee_id: str, name: str, department: str, email: str, phone: str, frames_b64: List[str]) -> Dict[str, Any]:
    """
    Enrolls user from multi-sample captures.
    """
    engine, spoof, gallery, cfg = get_ai_components()

    if not frames_b64:
        return {"success": False, "message": "No enrollment frames captured."}

    valid_embs = []
    best_face_crop = None
    scores = []

    with _lock:
        for b64 in frames_b64:
            frame = decode_image_base64(b64)
            if frame is None:
                continue
            obs = engine.analyze(frame)
            if obs.face is not None and obs.usable:
                scores.append(spoof.score(frame, obs.face.bbox))
                valid_embs.append(obs.face.normed_embedding)
                if best_face_crop is None:
                    x1, y1, x2, y2 = [int(v) for v in obs.face.bbox]
                    H, W = frame.shape[:2]
                    margin = int(0.2 * (y2 - y1))
                    crop = frame[max(0, y1-margin):min(H, y2+margin), max(0, x1-margin):min(W, x2+margin)]
                    if crop.size > 0:
                        best_face_crop = crop

    if len(valid_embs) < 2:
        return {"success": False, "message": "Not enough clear frontal frames detected. Please hold still and re-try."}

    # Verify Liveness
    median_score = float(np.median(scores))
    if median_score < cfg.live_score_thresh:
        return {"success": False, "message": f"Enrollment rejected: Liveness check failed (Score: {(median_score*100):.1f}%). Please ensure real person in good light."}

    # Cross-person duplicate check
    mean_emb = np.mean(valid_embs, axis=0)
    mean_emb = mean_emb / max(float(np.linalg.norm(mean_emb)), 1e-9)

    with _lock:
        other_gallery = Gallery(cfg.db_path, cfg)
        other_gallery.remove(name)
        m = other_gallery.identify(mean_emb.astype(np.float32))

        if m.score >= cfg.match_thresh and m.name != name and m.name != "Unknown":
            return {"success": False, "message": f"Face matches existing user '{m.name}' (Score: {m.score:.2f}). Cannot register duplicate."}

        # Save avatar
        avatar_url = ""
        if best_face_crop is not None:
            avatar_file = f"uploads/avatars/{employee_id}.jpg"
            cv2.imwrite(avatar_file, best_face_crop)
            avatar_url = f"/{avatar_file}"

        # Update Gallery
        gallery.remove(name)
        for e in valid_embs:
            gallery.add(name, e)
        gallery.save()

        # Update SQLite
        db.create_or_update_user(
            employee_id=employee_id,
            name=name,
            department=department,
            email=email,
            phone=phone,
            avatar_path=avatar_url,
            sample_count=len(valid_embs)
        )

    return {
        "success": True,
        "message": f"Successfully enrolled '{name}' with {len(valid_embs)} biometric samples!",
        "samples": len(valid_embs),
        "avatar": avatar_url
    }
