"""
face_system.py - Face recognition + anti-spoofing (liveness) system.

Pipeline per attempt:
  camera -> SCRFD detect (InsightFace) -> quality gate -> MiniFASNet ensemble
         -> randomized head-turn challenge -> ArcFace embedding (multi-frame)
         -> identity-continuity check -> gallery match (threshold + margin)

Setup:
  pip install insightface onnxruntime opencv-python "numpy<2" torch torchvision easydict tqdm
  git clone https://github.com/minivision-ai/Silent-Face-Anti-Spoofing
  (NVIDIA GPU: pip install onnxruntime-gpu instead of onnxruntime)

Commands:
  python face_system.py enroll alice --sessions 3
  python face_system.py verify
  python face_system.py list
  python face_system.py delete alice

IMPORTANT: run `calibrate.py` on your own data and update the thresholds in
Config. Default thresholds are sensible starting points, not final values.
"""
from __future__ import annotations

import argparse
import logging
import os
import queue
import random
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger("facesys")


# =============================================================================
# Configuration
# =============================================================================
@dataclass
class Config:
    # paths
    repo_dir: str = "Silent-Face-Anti-Spoofing"
    spoof_models: Tuple[str, ...] = (
        "2.7_80x80_MiniFASNetV2.pth",
        "4_0_0_80x80_MiniFASNetV1SE.pth",
    )
    db_path: str = "face_db.npz"
    log_path: str = "face_system.log"

    # runtime
    use_gpu: bool = True
    cam_index: int = 0
    det_size: Tuple[int, int] = (640, 640)
    enable_voice: bool = True
    voice_rate: int = 1                   # SAPI rate: -10 to 10 (1 is brisk and clear)

    # quality gate
    min_face_px: int = 90
    min_det_score: float = 0.65
    min_blur_var: float = 35.0            # Laplacian variance on 112x112 crop
    brightness_range: Tuple[float, float] = (50.0, 210.0)
    second_face_ratio: float = 0.40       # reject if 2nd face > 40% area of 1st
    max_frontal_offset: float = 0.22      # |turn ratio| allowed for "frontal"

    # liveness (passive)
    live_score_thresh: float = 0.68       # per-frame MiniFASNet "real" prob
    live_vote_ratio: float = 0.65         # fraction of frames that must pass
    live_min_frames: int = 5

    # liveness (active challenge)
    challenge_steps: int = 1              # 1 quick random turn challenge for fast flow
    turn_ratio: float = 0.20              # responsive natural turn angle
    center_ratio: float = 0.12            # return center threshold
    step_timeout: float = 6.0
    flip_directions: bool = False         # set True if left/right feel swapped

    # session
    frames_per_phase: int = 3             # 3 pre + 3 post = 6 frames total (fast & smooth)
    session_timeout: float = 25.0
    face_lost_sec: float = 1.5
    max_center_jump: float = 0.65         # face-center jump / face width per frame
    consistency_min: float = 0.50         # every frame vs. mean embedding

    # matching (ArcFace cosine similarity)
    match_thresh: float = 0.45
    margin: float = 0.08


# =============================================================================
# Background Voice Assistant (Native Windows SAPI)
# =============================================================================
class VoiceSpeaker:
    """Non-blocking, zero-latency native Windows SAPI voice speaker."""
    def __init__(self, enabled: bool = True, rate: int = 1):
        self.enabled = enabled
        self._voice = None
        if self.enabled:
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                self._voice = win32com.client.Dispatch("SAPI.SpVoice")
                self._voice.Rate = int(rate)
            except Exception as e:
                log.warning("Voice initialization warning: %s", e)
                self._voice = None

    def speak(self, text: Optional[str], interrupt: bool = True):
        if not self.enabled or not self._voice or not text:
            return
        try:
            # 1 = SVSFlagsAsync (background non-blocking playback)
            # 2 = SVSFPurgeBeforeSpeak (instantly clears previous utterance)
            flags = (1 | 2) if interrupt else 1
            self._voice.Speak(str(text), flags)
        except Exception as e:
            log.warning("Voice playback error: %s", e)

    def wait_done(self, timeout_ms: int = 2500):
        if not self.enabled or not self._voice:
            return
        try:
            self._voice.WaitUntilDone(int(timeout_ms))
        except Exception:
            pass

    def stop(self):
        if not self.enabled or not self._voice:
            return
        try:
            self._voice.Speak("", 1 | 2)
        except Exception:
            pass


# =============================================================================
# Anti-spoof (MiniFASNet ensemble, models cached in memory)
# =============================================================================
class SpoofDetector:
    def __init__(self, cfg: Config):
        import torch

        self.torch = torch
        self.device = torch.device(
            "cuda" if cfg.use_gpu and torch.cuda.is_available() else "cpu")

        repo = os.path.abspath(cfg.repo_dir)
        if not os.path.isdir(repo):
            raise FileNotFoundError(
                f"'{cfg.repo_dir}' not found. Run: git clone "
                "https://github.com/minivision-ai/Silent-Face-Anti-Spoofing")
        if repo not in sys.path:
            sys.path.insert(0, repo)

        from src.data_io import transform as trans
        from src.generate_patches import CropImage
        from src.model_lib.MiniFASNet import (MiniFASNetV1, MiniFASNetV1SE,
                                              MiniFASNetV2, MiniFASNetV2SE)
        from src.utility import get_kernel, parse_model_name

        mapping = {"MiniFASNetV1": MiniFASNetV1, "MiniFASNetV2": MiniFASNetV2,
                   "MiniFASNetV1SE": MiniFASNetV1SE,
                   "MiniFASNetV2SE": MiniFASNetV2SE}
        self.cropper = CropImage()
        self.to_tensor = trans.ToTensor()
        self.nets = []
        for name in cfg.spoof_models:
            path = os.path.join(repo, "resources", "anti_spoof_models", name)
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Spoof model missing: {path}")
            h, w, mtype, scale = parse_model_name(name)
            net = mapping[mtype](conv6_kernel=get_kernel(h, w)).to(self.device)
            state = torch.load(path, map_location=self.device)
            state = OrderedDict(
                (k[7:] if k.startswith("module.") else k, v)
                for k, v in state.items())
            net.load_state_dict(state)
            net.eval()
            self.nets.append((net, h, w, scale))
        log.info("Loaded %d anti-spoof models on %s", len(self.nets), self.device)

    def score(self, frame: np.ndarray, bbox_xyxy) -> float:
        """Mean probability that the face is REAL (class 1), in [0, 1]."""
        x1, y1, x2, y2 = [float(v) for v in bbox_xyxy]
        bbox = [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]  # x, y, w, h
        probs = []
        with self.torch.no_grad():
            for net, h, w, scale in self.nets:
                patch = self.cropper.crop(
                    org_img=frame, bbox=bbox, scale=scale,
                    out_w=w, out_h=h, crop=scale is not None)
                t = self.to_tensor(patch).unsqueeze(0).to(self.device)
                p = self.torch.softmax(net(t), dim=1)[0].cpu().numpy()
                probs.append(p)
        return float(np.mean(probs, axis=0)[1])


# =============================================================================
# Face engine (detection + alignment + ArcFace embedding + quality gate)
# =============================================================================
@dataclass
class Observation:
    face: Optional[object]
    reason: str                 # "ok" or why the frame is unusable
    usable: bool = False        # passes quality gate
    frontal: bool = False
    turn_ratio: float = 0.0     # >0: nose toward image-right


def _area(f) -> float:
    return float((f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


def turn_ratio_from_kps(kps: np.ndarray) -> float:
    """Horizontal nose offset relative to eye midpoint, normalized by eye
    distance. Roughly 0 when frontal. Sign: positive = nose toward image right
    (the person turned toward THEIR left when facing the camera)."""
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    eye_dist = max(abs(right_eye[0] - left_eye[0]), 1e-6)
    mid_x = (left_eye[0] + right_eye[0]) / 2.0
    return float((nose[0] - mid_x) / eye_dist)


class FaceEngine:
    def __init__(self, cfg: Config):
        from insightface.app import FaceAnalysis

        self.cfg = cfg
        providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                     if cfg.use_gpu else ["CPUExecutionProvider"])
        self.app = FaceAnalysis(
            name="buffalo_l",
            allowed_modules=["detection", "recognition"],
            providers=providers)
        self.app.prepare(ctx_id=0 if cfg.use_gpu else -1, det_size=cfg.det_size)

    def largest_face(self, frame: np.ndarray):
        """Raw largest face with no quality gating (used by calibration)."""
        faces = self.app.get(frame)
        return max(faces, key=_area) if faces else None

    def _quality_reason(self, frame, f) -> Optional[str]:
        c = self.cfg
        x1, y1, x2, y2 = f.bbox
        w, h = x2 - x1, y2 - y1
        H, W = frame.shape[:2]
        if min(w, h) < c.min_face_px:
            return "move closer"
        if f.det_score < c.min_det_score:
            return "low detection confidence"
        tol_x, tol_y = 0.02 * W, 0.02 * H
        if x1 < -tol_x or y1 < -tol_y or x2 > W + tol_x or y2 > H + tol_y:
            return "face cut off, center yourself"
        crop = frame[max(int(y1), 0):int(y2), max(int(x1), 0):int(x2)]
        if crop.size == 0:
            return "invalid face region"
        gray = cv2.cvtColor(cv2.resize(crop, (112, 112)), cv2.COLOR_BGR2GRAY)
        if cv2.Laplacian(gray, cv2.CV_64F).var() < c.min_blur_var:
            return "image blurry, hold still"
        mean = float(gray.mean())
        if mean < c.brightness_range[0]:
            return "too dark"
        if mean > c.brightness_range[1]:
            return "too bright / glare"
        return None

    def analyze(self, frame: np.ndarray) -> Observation:
        faces = self.app.get(frame)
        if not faces:
            return Observation(None, "no face")
        faces.sort(key=_area, reverse=True)
        if len(faces) > 1 and _area(faces[1]) > self.cfg.second_face_ratio * _area(faces[0]):
            return Observation(None, "multiple faces")
        f = faces[0]
        ratio = turn_ratio_from_kps(f.kps)
        reason = self._quality_reason(frame, f)
        return Observation(
            face=f, reason=reason or "ok", usable=reason is None,
            frontal=abs(ratio) <= self.cfg.max_frontal_offset, turn_ratio=ratio)


# =============================================================================
# Gallery (atomic saves, no pickle)
# =============================================================================
@dataclass
class MatchResult:
    name: str
    score: float
    second: float
    accepted: bool
    reason: str


class Gallery:
    def __init__(self, path: str, cfg: Config):
        self.path, self.cfg = path, cfg
        self.names: List[str] = []
        self.embs = np.zeros((0, 512), dtype=np.float32)
        if os.path.exists(path):
            data = np.load(path, allow_pickle=False)
            self.names = [str(n) for n in data["names"]]
            self.embs = data["embs"].astype(np.float32)

    def add(self, name: str, emb: np.ndarray):
        self.names.append(name)
        self.embs = np.vstack([self.embs, emb.astype(np.float32)[None]])

    def remove(self, name: str) -> int:
        keep = [i for i, n in enumerate(self.names) if n != name]
        removed = len(self.names) - len(keep)
        self.names = [self.names[i] for i in keep]
        self.embs = self.embs[keep] if keep else np.zeros((0, 512), np.float32)
        return removed

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as fh:
            np.savez(fh, names=np.array(self.names, dtype=str), embs=self.embs)
        os.replace(tmp, self.path)

    def identify(self, emb: np.ndarray) -> MatchResult:
        if not self.names:
            return MatchResult("Unknown", 0.0, -1.0, False, "gallery is empty")
        sims = self.embs @ emb
        per: dict = {}
        for n, s in zip(self.names, sims):
            per.setdefault(n, []).append(float(s))
        scored = []
        for n, v in per.items():
            v.sort(reverse=True)
            scored.append((n, float(np.mean(v[:2]))))   # mean of top-2 samples
        scored.sort(key=lambda x: -x[1])
        best_n, best = scored[0]
        second = scored[1][1] if len(scored) > 1 else -1.0
        if best < self.cfg.match_thresh:
            return MatchResult("Unknown", best, second, False, "below threshold")
        if len(scored) > 1 and best - second < self.cfg.margin:
            return MatchResult("Unknown", best, second, False,
                               "ambiguous: runner-up too close")
        return MatchResult(best_n, best, second, True, "ok")


# =============================================================================
# Live session: quality -> passive liveness -> active challenge -> embedding
# =============================================================================
@dataclass
class SessionResult:
    live: bool
    embedding: Optional[np.ndarray]
    message: str
    stats: dict


def _normalize(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-9)


def make_challenge(n: int) -> List[str]:
    steps: List[str] = []
    while len(steps) < n:
        c = random.choice(["left", "right"])
        if not steps or c != steps[-1]:
            steps.append(c)
    return steps


def _draw(frame, text, sub="", is_warning=False):
    disp = cv2.flip(frame, 1)  # mirror preview so left/right feel natural
    H, W = disp.shape[:2]
    # Semi-transparent top overlay for readability
    overlay = disp.copy()
    cv2.rectangle(overlay, (0, 0), (W, 90), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.75, disp, 0.25, 0, disp)

    color = (0, 165, 255) if is_warning else (0, 255, 0)
    cv2.putText(disp, text, (20, 42), cv2.FONT_HERSHEY_DUPLEX, 0.95, color, 2, cv2.LINE_AA)
    if sub:
        cv2.putText(disp, sub, (20, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220, 220, 220), 1, cv2.LINE_AA)
    cv2.imshow("face_system  (Esc to cancel)", disp)
    return cv2.waitKey(1) & 0xFF


def run_session(cap, engine: FaceEngine, spoof: SpoofDetector, cfg: Config,
                challenge: bool = True, show: bool = True,
                voice: Optional[VoiceSpeaker] = None) -> SessionResult:
    steps = make_challenge(cfg.challenge_steps) if challenge else []
    pre_embs: List[np.ndarray] = []
    post_embs: List[np.ndarray] = []
    scores: List[float] = []
    phase, step_idx, need_center = "pre", 0, False
    t_start = t_seen = step_t0 = time.time()
    prev_center, prev_w = None, None
    msg, sub, is_warning = "LOOK AT CAMERA", "Look directly at camera", False
    fail = None

    if voice is not None:
        voice.speak("Look at the camera")

    while time.time() - t_start < cfg.session_timeout:
        ok, frame = cap.read()
        if not ok:
            continue
        now = time.time()
        obs = engine.analyze(frame)

        if obs.face is None:
            msg = obs.reason.upper()
            sub = "Position face inside frame"
            is_warning = True
            if phase != "pre" and now - t_seen > cfg.face_lost_sec:
                fail = "face lost during session"
                break
            if phase == "pre" and pre_embs and now - t_seen > cfg.face_lost_sec:
                fail = "face lost during session"
                break
        else:
            f = obs.face
            t_seen = now
            is_warning = False
            # identity-swap guard: the face must move continuously
            cx, cy = (f.bbox[0] + f.bbox[2]) / 2, (f.bbox[1] + f.bbox[3]) / 2
            w = f.bbox[2] - f.bbox[0]
            if prev_center is not None:
                jump = np.hypot(cx - prev_center[0], cy - prev_center[1]) / max(prev_w, 1.0)
                if jump > cfg.max_center_jump:
                    fail = "tracking jump (possible face swap)"
                    break
            prev_center, prev_w = (cx, cy), w

            if phase == "pre":
                if obs.usable and obs.frontal:
                    scores.append(spoof.score(frame, f.bbox))
                    pre_embs.append(f.normed_embedding)
                    msg = "LOOK AT CAMERA"
                    sub = f"Readying... ({len(pre_embs)}/{cfg.frames_per_phase})"
                else:
                    msg = (obs.reason if not obs.usable else "look straight").upper()
                    sub = "Center your face in good lighting"
                    is_warning = True

                if len(pre_embs) >= cfg.frames_per_phase:
                    phase = "challenge" if steps else "post"
                    step_t0 = now
                    if phase == "challenge" and voice is not None:
                        want = steps[step_idx]
                        shown = "right" if (cfg.flip_directions and want == "left") else ("left" if (cfg.flip_directions and want == "right") else want)
                        voice.speak(f"Turn {shown}")
                    elif phase == "post" and voice is not None:
                        voice.speak("Hold still")

            elif phase == "challenge":
                want = steps[step_idx]
                shown = "right" if (cfg.flip_directions and want == "left") else ("left" if (cfg.flip_directions and want == "right") else want)
                r = obs.turn_ratio

                if need_center:
                    msg = "LOOK STRAIGHT"
                    sub = f"Return to center ({step_idx}/{len(steps)})"
                    if abs(r) <= cfg.center_ratio:
                        need_center = False
                        step_t0 = now
                        if step_idx < len(steps):
                            next_want = steps[step_idx]
                            next_shown = "right" if (cfg.flip_directions and next_want == "left") else ("left" if (cfg.flip_directions and next_want == "right") else next_want)
                            if voice is not None:
                                voice.speak(f"Turn {next_shown}")
                else:
                    arrow = "<<<" if shown == "left" else ">>>"
                    msg = f"{arrow} TURN HEAD {shown.upper()} {arrow}"
                    sub = f"Turn head to your {shown}"
                    hit = (r >= cfg.turn_ratio) if want == "left" else (r <= -cfg.turn_ratio)
                    if cfg.flip_directions:
                        hit = (r <= -cfg.turn_ratio) if want == "left" else (r >= cfg.turn_ratio)
                    if hit:
                        step_idx += 1
                        if step_idx >= len(steps):
                            phase = "post"
                            if voice is not None:
                                voice.speak("Hold still")
                        else:
                            need_center = True
                            if voice is not None:
                                voice.speak("Look straight")

                if phase == "challenge" and now - step_t0 > cfg.step_timeout:
                    fail = "challenge timeout"
                    break

            elif phase == "post":
                msg = "HOLD STILL"
                sub = f"Verifying... ({len(post_embs)}/{cfg.frames_per_phase})"
                if obs.usable and obs.frontal:
                    scores.append(spoof.score(frame, f.bbox))
                    post_embs.append(f.normed_embedding)
                if len(post_embs) >= cfg.frames_per_phase:
                    phase = "done"

        if show:
            if _draw(frame, msg, sub, is_warning=is_warning) == 27:
                fail = "cancelled"
                break
        if phase == "done":
            break

    # ----------------------------- decision ---------------------------------
    stats = {"frames_scored": len(scores), "phase": phase, "steps": steps}
    if fail:
        return SessionResult(False, None, fail, stats)
    if phase != "done":
        return SessionResult(False, None, "session timed out", stats)
    if len(scores) < cfg.live_min_frames:
        return SessionResult(False, None, "not enough good frames", stats)

    arr = np.array(scores)
    stats.update(live_median=float(np.median(arr)),
                 live_pass_ratio=float((arr >= cfg.live_score_thresh).mean()))
    if stats["live_pass_ratio"] < cfg.live_vote_ratio or \
            stats["live_median"] < cfg.live_score_thresh:
        return SessionResult(False, None, "SPOOF suspected (passive check)", stats)

    E = np.stack(pre_embs + post_embs)
    mean = _normalize(E.mean(0))
    stats["min_consistency"] = float((E @ mean).min())
    if stats["min_consistency"] < cfg.consistency_min:
        return SessionResult(False, None, "inconsistent identity across frames", stats)
    if pre_embs and post_embs:
        cross = float(_normalize(np.mean(pre_embs, 0)) @ _normalize(np.mean(post_embs, 0)))
        stats["pre_post_similarity"] = cross
        if cross < cfg.consistency_min:
            return SessionResult(False, None, "different person before/after challenge", stats)
    return SessionResult(True, mean.astype(np.float32), "ok", stats)


# =============================================================================
# CLI
# =============================================================================
def open_camera(cfg: Config):
    cap = cv2.VideoCapture(cfg.cam_index)
    if not cap.isOpened():
        raise RuntimeError("Cannot open camera (try --cam 1 or close other apps).")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    for _ in range(10):  # let auto-exposure settle
        cap.read()
    return cap


def cmd_enroll(cfg, name, sessions, challenge):
    voice = VoiceSpeaker(enabled=cfg.enable_voice, rate=cfg.voice_rate)
    engine, spoof = FaceEngine(cfg), SpoofDetector(cfg)
    gallery = Gallery(cfg.db_path, cfg)
    cap = open_camera(cfg)
    new_embs: List[np.ndarray] = []
    attempts = 0
    try:
        while len(new_embs) < sessions and attempts < sessions * 3:
            attempts += 1
            if sessions > 1:
                print(f"\nSession {len(new_embs) + 1}/{sessions} (vary angle/lighting slightly)")
            res = run_session(cap, engine, spoof, cfg, challenge=challenge, voice=voice)
            if not res.live:
                print("  rejected:", res.message)
                log.info("ENROLL_REJECT name=%s reason=%s stats=%s", name, res.message, res.stats)
                voice.speak("Session rejected, please try again")
                time.sleep(1.0)
                continue
            if new_embs and min(float(e @ res.embedding) for e in new_embs) < cfg.consistency_min:
                print("  rejected: different person than earlier sessions")
                voice.speak("Different person detected")
                time.sleep(1.0)
                continue
            other = Gallery(cfg.db_path, cfg)
            other.remove(name)
            m = other.identify(res.embedding)
            if m.score >= cfg.match_thresh and m.name != name and m.name != "Unknown":
                print(f"  rejected: face already enrolled as '{m.name}' (score {m.score:.2f})")
                voice.speak(f"Face already registered as {m.name}")
                time.sleep(1.0)
                continue
            new_embs.append(res.embedding)
            print("  accepted")
            if len(new_embs) < sessions:
                voice.speak("Session accepted, next session")
                time.sleep(0.5)
    finally:
        cap.release()
        cv2.destroyAllWindows()

    if len(new_embs) < sessions:
        print(f"\nOnly {len(new_embs)}/{sessions} sessions succeeded - nothing saved.")
        voice.speak("Enrollment failed")
        voice.wait_done(1500)
        return 1
    for e in new_embs:
        gallery.add(name, e)
    gallery.save()
    log.info("ENROLL_OK name=%s samples=%d", name, len(new_embs))
    print(f"\nEnrolled '{name}' with {len(new_embs)} samples.")
    voice.speak(f"Welcome {name}! Registration complete.")
    voice.wait_done(2500)
    return 0


def cmd_verify(cfg, challenge):
    voice = VoiceSpeaker(enabled=cfg.enable_voice, rate=cfg.voice_rate)
    engine, spoof = FaceEngine(cfg), SpoofDetector(cfg)
    gallery = Gallery(cfg.db_path, cfg)
    cap = open_camera(cfg)
    try:
        res = run_session(cap, engine, spoof, cfg, challenge=challenge, voice=voice)
    finally:
        cap.release()
        cv2.destroyAllWindows()

    if not res.live:
        print("REJECTED:", res.message)
        log.info("VERIFY_REJECT reason=%s stats=%s", res.message, res.stats)
        voice.speak("Verification failed")
        voice.wait_done(1800)
        return 1

    m = gallery.identify(res.embedding)
    print(f"{'ACCEPTED' if m.accepted else 'REJECTED'}: {m.name} "
          f"(score={m.score:.3f}, runner-up={m.second:.3f}, {m.reason})")
    log.info("VERIFY_%s name=%s score=%.3f second=%.3f reason=%s stats=%s",
             "OK" if m.accepted else "FAIL", m.name, m.score, m.second, m.reason, res.stats)

    if m.accepted:
        voice.speak(f"Welcome {m.name}!")
    else:
        voice.speak("Access denied")
    voice.wait_done(2200)
    return 0 if m.accepted else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enroll"); e.add_argument("name")
    e.add_argument("--sessions", type=int, default=1,
                   help="number of enrollment passes (default: 1 for fast enrollment)")
    sub.add_parser("verify")
    sub.add_parser("list")
    d = sub.add_parser("delete"); d.add_argument("name")
    for p in (e, sub.choices["verify"]):
        p.add_argument("--no-challenge", action="store_true",
                       help="skip head-turn challenge (testing only)")
    ap.add_argument("--flip-turn", action="store_true",
                    help="invert left/right head turn directions if camera mirror orientation feels swapped")
    ap.add_argument("--no-voice", action="store_true",
                    help="disable text-to-speech voice guidance")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--cam", type=int, default=0)
    args = ap.parse_args()

    cfg = Config(use_gpu=not args.cpu, cam_index=args.cam,
                 enable_voice=not args.no_voice, flip_directions=args.flip_turn)
    logging.basicConfig(
        filename=cfg.log_path, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "list":
        g = Gallery(cfg.db_path, cfg)
        counts: dict = {}
        for n in g.names:
            counts[n] = counts.get(n, 0) + 1
        for n, c in sorted(counts.items()):
            print(f"{n}: {c} samples")
        if not counts:
            print("(empty)")
        return 0
    if args.cmd == "delete":
        g = Gallery(cfg.db_path, cfg)
        n = g.remove(args.name)
        g.save()
        print(f"Removed {n} samples for '{args.name}'.")
        return 0
    if args.cmd == "enroll":
        return cmd_enroll(cfg, args.name, args.sessions, not args.no_challenge)
    return cmd_verify(cfg, not args.no_challenge)


if __name__ == "__main__":
    sys.exit(main())
