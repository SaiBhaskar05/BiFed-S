# BiFed-S — Biometric Face Recognition & Continuous Attendance System

> **Enterprise-grade real-time face recognition attendance system with multi-layered anti-spoofing (Presentation Attack Detection), continuous kiosk scanning, and a full admin management portal.**

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-2.0+-EE4C2C?logo=pytorch&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Why These Thresholds?](#why-these-thresholds)
- [Installation & Setup](#installation--setup)
- [Commands to Execute](#commands-to-execute)
- [Default Credentials](#default-credentials)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Calibration Guide](#calibration-guide)
- [Future Improvements](#future-improvements)
- [License](#license)

---

## Overview

**BiFed-S** eliminates manual attendance tracking entirely. Employees simply walk up to a kiosk camera — the system instantly detects their face, verifies they are a **real person** (not a photograph, screen replay, or mask), identifies **who they are** from a registered gallery, and logs their attendance — all in under **150 milliseconds**.

The system is split into two completely independent portals:

| Portal | Purpose |
|---|---|
| **Admin Management Portal** | Register employees via webcam, manage user database, view attendance analytics, export CSV reports, and tune AI thresholds |
| **Continuous Attendance Kiosk** | Full-screen 24/7 scanning terminal — fully autonomous face detection, anti-spoofing, identification, and attendance logging with audio-visual feedback |

---

## Key Features

- **Real-Time Face Recognition** — ArcFace (InsightFace `buffalo_l`) generates 512-dimensional face embeddings for highly accurate 1:N identification
- **Dual-Model Anti-Spoofing** — MiniFASNet ensemble (V2 + V1SE) at two crop scales detects printed photos, screen replays, video attacks, and 3D masks
- **Continuous Kiosk Scanning** — The scanner runs non-stop at ~10 FPS with a sci-fi HUD overlay; employees don't need to press anything — just look at the camera
- **Active Liveness Challenge (CLI)** — Randomized head-turn challenges tracked via 5-point facial landmarks provide an extra verification layer
- **Quality Gate Pipeline** — 7 automated checks (face size, blur, brightness, confidence, pose, boundaries, multi-face) ensure only high-quality frames are processed
- **Cooldown System** — Configurable timer prevents duplicate check-ins from continuous scanning
- **Late Detection** — Automatic "Present" vs "Late" status based on admin-configurable cutoff time
- **CSV Export** — One-click attendance report download from the admin dashboard
- **Voice Guidance** — Native Windows SAPI text-to-speech guides users through enrollment and verification
- **Glassmorphism UI** — Modern dark-themed interface with sci-fi HUD elements, animated feedback, and Web Audio synthesized sound effects

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser (Frontend)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Portal Select │  │ Admin Portal │  │ Kiosk Scanner HUD │  │
│  │  (Landing)    │  │ (Dashboard)  │  │ (24/7 Continuous) │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘  │
└─────────┼─────────────────┼───────────────────┼─────────────┘
          │                 │                   │
          ▼                 ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│              FastAPI Backend (app.py)                        │
│  ┌─────────────────┐  ┌──────────────────────────────────┐  │
│  │ Session Auth     │  │ REST API Endpoints (19 routes)   │  │
│  │ (Cookie-based)   │  │ Admin APIs + Kiosk APIs          │  │
│  └─────────────────┘  └──────────────┬───────────────────┘  │
└──────────────────────────────────────┼──────────────────────┘
                                       │
          ┌────────────────────────────┼────────────────┐
          ▼                            ▼                ▼
┌──────────────────┐  ┌──────────────────────┐  ┌─────────────┐
│  AI Engine        │  │  Database Layer       │  │  Gallery    │
│  (ai_service.py)  │  │  (database.py)        │  │  (NPZ file) │
│                   │  │                       │  │             │
│  ┌─────────────┐  │  │  SQLite Tables:       │  │  Names[]    │
│  │ FaceEngine  │  │  │  • admins             │  │  Embeddings │
│  │ (InsightFace)│  │  │  • kiosks             │  │  (512-d)    │
│  ├─────────────┤  │  │  • users              │  └─────────────┘
│  │ SpoofDetect │  │  │  • attendance_logs    │
│  │ (MiniFASNet)│  │  │  • settings           │
│  └─────────────┘  │  └──────────────────────┘
└──────────────────┘
```

---

## Technology Stack

| Layer | Technology | Role |
|---|---|---|
| Web Framework | FastAPI + Uvicorn | Async Python ASGI server for real-time AI workloads |
| Templating | Jinja2 | Server-side HTML rendering |
| Database | SQLite 3 | Embedded zero-config persistence |
| Face Detection | SCRFD (InsightFace `buffalo_l`) | Fast face detection with 5-point landmarks |
| Face Recognition | ArcFace (InsightFace `buffalo_l`) | 512-d cosine-similarity embeddings |
| Anti-Spoofing | MiniFASNet V2 + V1SE | Passive presentation attack detection ensemble |
| Deep Learning | PyTorch + ONNX Runtime | Model inference with GPU acceleration |
| Computer Vision | OpenCV | Image I/O, blur detection, cropping |
| Voice | Windows SAPI (COM) | Non-blocking text-to-speech guidance |
| Frontend | Vanilla JS + CSS | Glassmorphism dark UI, canvas HUD, Web Audio API |
| Icons | Lucide Icons | Modern SVG icon set (CDN) |

---

## Why These Thresholds?

Every threshold in this system was chosen based on well-established principles in biometric research. Here's the rationale behind each:

### Face Recognition Thresholds

| Parameter | Value | Rationale |
|---|---|---|
| `match_thresh = 0.45` | **Minimum cosine similarity for identity match** | ArcFace cosine similarities typically range from 0.2–0.4 for impostors and 0.5–0.8 for genuine matches. A threshold of 0.45 sits in the natural gap between these distributions, catching most genuine users while rejecting strangers. Academic benchmarks (LFW, CFP-FP) show ArcFace EER typically occurs around 0.35–0.50 depending on the dataset. **0.45 is a balanced starting point** — strict enough to prevent false accepts, lenient enough to not reject enrolled users under normal lighting variation. |
| `margin = 0.08` | **Required gap between #1 and #2 match** | When two enrolled people look somewhat similar, the system needs to be confident about which one it is. If the best match scores 0.52 and the runner-up scores 0.48 (gap = 0.04), that's dangerously ambiguous. An 0.08 margin ensures the system only accepts identifications where the winner is **clearly ahead** of all alternatives. This is analogous to the "reject option" in pattern recognition theory. |
| `consistency_min = 0.50` | **Per-frame vs. mean embedding consistency** | During a multi-frame session (enrollment or CLI verification), every individual frame's embedding must correlate at least 0.50 with the mean embedding. This catches two attacks: (1) swapping a different person's face mid-session, and (2) environmental anomalies producing unreliable embeddings. 0.50 is deliberately lower than `match_thresh` because intra-session variation is expected. |

### Anti-Spoofing (PAD) Thresholds

| Parameter | Value | Rationale |
|---|---|---|
| `live_score_thresh = 0.68` | **Minimum "real" probability per frame** | MiniFASNet outputs a softmax probability [spoof, real]. Research on the OULU-NPU and CASIA-FASD benchmarks shows these models achieve EER around 2–5%. At a threshold of 0.68, the model is saying "I'm at least 68% confident this is a real face." This is **below the 0.80+ range** intentionally — being too strict causes real users in poor lighting to be falsely rejected. 0.68 catches obvious attacks (photos typically score 0.1–0.4) while tolerating natural variation in live faces (which typically score 0.75–0.98). |
| `live_vote_ratio = 0.65` | **Fraction of frames that must pass** | Not every frame of a real person will score above 0.68 — motion blur, a brief shadow, or head angle can cause momentary drops. Requiring 65% (not 100%) of frames to pass provides robustness against these transient quality issues while still catching sustained spoof attacks where most frames fail consistently. |
| `live_min_frames = 5` | **Minimum frames for a liveness decision** | A single frame can be noisy. With 5+ frames, statistical voting becomes meaningful. The `live_vote_ratio` of 0.65 over 5 frames means at least 4 out of 5 must pass — a reasonable balance. |

### Quality Gate Thresholds

| Parameter | Value | Rationale |
|---|---|---|
| `min_face_px = 90` | **Minimum face width/height in pixels** | ArcFace internally aligns faces to 112×112. If the detected face is smaller than 90px, upscaling introduces artifacts that degrade embedding quality. 90px ensures the crop is near-native resolution for the recognition model. |
| `min_det_score = 0.65` | **Minimum SCRFD detection confidence** | SCRFD sometimes produces low-confidence detections for non-face objects (hands, posters, screen edges). 0.65 filters these false detections while retaining faces detected at moderate angles or partial occlusion. |
| `min_blur_var = 35.0` | **Laplacian variance threshold** | The Laplacian operator highlights edges; its variance measures image sharpness. Sharp face images typically have variance 50–200+, while motion-blurred frames drop to 10–30. A threshold of 35 rejects obviously blurry frames without being overly strict on slight natural motion. |
| `brightness_range = (50, 210)` | **Mean pixel intensity limits** | A mean below 50 indicates very dark images (underexposed), above 210 indicates severe overexposure or glare. Both conditions cause ArcFace to produce unreliable embeddings. The range 50–210 covers most normal indoor and outdoor lighting. |
| `max_frontal_offset = 0.22` | **Maximum head turn ratio for "frontal"** | The turn ratio measures how far the nose deviates from the eye midpoint, normalized by inter-eye distance. At 0.22, a person can have a slight natural head tilt (~12–15°) and still be considered frontal. This prevents overly strict frontality requirements that would slow down the kiosk flow. |
| `second_face_ratio = 0.40` | **Multi-face rejection threshold** | If a second person's face is more than 40% the size of the primary face, the frame is ambiguous — the system might embed the wrong person. Below 40%, the second face is likely a background bystander and can be safely ignored. |

### Active Challenge Thresholds (CLI Mode)

| Parameter | Value | Rationale |
|---|---|---|
| `turn_ratio = 0.20` | **Required head turn for challenge** | A nose offset ratio of 0.20 corresponds to roughly a 12–15° head turn — enough to prove 3D head movement (impossible for a flat photo) without asking for an extreme turn that feels uncomfortable. |
| `center_ratio = 0.12` | **Return-to-center threshold** | After turning, the user must look straight again. 0.12 is slightly tighter than `max_frontal_offset` to ensure a genuine return to center, not just a partial turn-back. |
| `step_timeout = 6.0s` | **Time limit per challenge step** | 6 seconds is generous enough for elderly or less tech-savvy users to complete a head turn, but short enough that an attacker can't spend unlimited time trying to manipulate a photo/screen to pass. |

> **Important:** These are **calibrated starting points**, not final values. Run `calibrate.py` with images from your actual deployment camera to find optimal thresholds for your specific environment.

---

## Installation & Setup

### Prerequisites

- Python 3.9 or higher
- NVIDIA GPU (recommended for real-time performance) or CPU fallback
- Webcam / IP camera
- Windows OS (for SAPI voice guidance; other features work cross-platform)

### Step-by-Step Setup

```bash
# 1. Clone this repository
git clone https://github.com/SaiBhaskar05/BiFed-S.git
cd BiFed-S

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

# 3. Install core dependencies
pip install fastapi uvicorn jinja2 python-multipart pydantic starlette

# 4. Install AI/ML dependencies
pip install insightface onnxruntime opencv-python "numpy<2" torch torchvision easydict tqdm

# 5. (GPU Users) Replace onnxruntime with GPU version
pip uninstall onnxruntime
pip install onnxruntime-gpu

# 6. (Optional) Install voice support (Windows only)
pip install pywin32

# 7. The Silent-Face-Anti-Spoofing models are included in this repo
#    No additional download needed — models are in:
#    Silent-Face-Anti-Spoofing/resources/anti_spoof_models/
```

---

## Commands to Execute

### Starting the System

```bash
# Start the web server (development mode with auto-reload)
python app.py
# → Server runs at http://localhost:8000

# OR start with uvicorn directly
uvicorn app:app --host 0.0.0.0 --port 8000 --reload

# Production mode (no reload, optimized)
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

> **Note:** Use `--workers 1` in production — AI models are loaded per-process, and multiple workers would duplicate GPU memory usage.

### Command-Line Interface (Direct Camera Mode)

```bash
# Enroll a new person via CLI (1 session, default)
python face_system.py enroll "Alice"

# Enroll with 3 varied sessions for higher accuracy
python face_system.py enroll "Alice" --sessions 3

# Verify identity via CLI (with head-turn challenge)
python face_system.py verify

# Verify without the head-turn challenge (testing only)
python face_system.py verify --no-challenge

# List all enrolled people
python face_system.py list

# Delete a person from the gallery
python face_system.py delete "Alice"

# Use CPU instead of GPU
python face_system.py verify --cpu

# Use a different camera index
python face_system.py verify --cam 1

# Flip left/right directions if camera mirror feels swapped
python face_system.py verify --flip-turn

# Disable voice guidance
python face_system.py verify --no-voice
```

### Calibration (Tune Thresholds to Your Environment)

```bash
# Step 1: Prepare calibration data
# Create folders:
#   data/pad/real/    → photos of real people taken with YOUR camera
#   data/pad/spoof/   → photos of attack attempts (printed photos, phone screens)
#   data/faces/alice/  → 5+ varied images of person "alice"
#   data/faces/bob/    → 5+ varied images of person "bob"

# Step 2: Run PAD (anti-spoofing) calibration
python calibrate.py pad --dir data/pad
# → Outputs EER and threshold recommendations for live_score_thresh

# Step 3: Run recognition calibration
python calibrate.py recog --dir data/faces
# → Outputs EER and threshold recommendations for match_thresh

# Step 4: Apply calibrated values in the Admin Dashboard Settings panel
# OR update Config defaults in face_system.py
```

---

## Default Credentials

| Portal | Credential | Value |
|---|---|---|
| Admin Login | Username | `admin` |
| Admin Login | Password | `admin123` |
| Kiosk Login | PIN Code | `1234` |

> ⚠️ **Change these immediately after first deployment!**

---

## Project Structure

```
BiFed-S/
├── app.py                    # FastAPI main application (routes + APIs)
├── face_system.py            # Core AI engine (detection, recognition, anti-spoofing, liveness)
├── ai_service.py             # Thread-safe bridge between web API and AI models
├── database.py               # SQLite persistence layer (schema, CRUD, stats)
├── calibrate.py              # Offline threshold calibration utility
├── templates/                # Jinja2 HTML templates
│   ├── portal_select.html    # Landing page (Admin vs Kiosk)
│   ├── admin_login.html      # Admin credential login
│   ├── admin_dashboard.html  # Full admin management panel
│   ├── kiosk_login.html      # Kiosk PIN authentication
│   └── kiosk_scanner.html    # Real-time biometric scanner HUD
├── static/
│   ├── css/                  # Stylesheets (main, admin, auth, kiosk)
│   ├── js/                   # Client-side logic (admin, kiosk, sounds)
│   └── sounds/               # Audio assets directory
├── Silent-Face-Anti-Spoofing/ # Anti-spoofing models & source
│   ├── resources/
│   │   ├── anti_spoof_models/ # MiniFASNet V2 + V1SE weights (.pth)
│   │   └── detection_model/   # RetinaFace detection model
│   └── src/                   # MiniFASNet model definitions & utilities
├── uploads/                   # Runtime: avatars & verification snapshots
├── .gitignore
└── README.md
```

---

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/admin/login` | Admin login (username + password) |
| `GET` | `/admin/logout` | Admin session logout |
| `POST` | `/api/kiosk/login` | Kiosk login (PIN code) |
| `GET` | `/kiosk/logout` | Kiosk session logout |

### Admin Management (requires admin session)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/admin/enroll` | Enroll new employee with webcam frames |
| `GET` | `/api/admin/users` | List all registered users |
| `DELETE` | `/api/admin/users/{id}` | Delete user from database and gallery |
| `GET` | `/api/admin/stats` | Dashboard statistics |
| `GET` | `/api/admin/attendance` | Attendance log history |
| `GET` | `/api/admin/export-attendance` | Download attendance CSV |
| `POST` | `/api/admin/settings` | Update AI thresholds and system settings |

### Kiosk Operations

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/kiosk/process-frame` | Real-time face tracking (~15–30ms) |
| `POST` | `/api/kiosk/verify` | Full identity verification + attendance log |
| `GET` | `/api/kiosk/today-logs` | Today's check-in feed |

---

## Calibration Guide

The default thresholds work well in typical office environments, but **calibrating with your own data significantly improves accuracy**:

### PAD Calibration Output Explained

```
EER ~ 2.50% at threshold 0.720        ← Equal Error Rate and its threshold
Target APCER   threshold   resulting BPCER
   5.0%        0.650       1.20%          ← If you accept 5% of attacks, 1.2% of real users are rejected
   1.0%        0.720       3.50%          ← If you accept 1% of attacks, 3.5% of real users are rejected
   0.1%        0.810       8.40%          ← Maximum security: almost no attacks pass, but 8.4% of real users are rejected
```

- **APCER** = Attack Presentation Classification Error Rate (attacks wrongly accepted)
- **BPCER** = Bona Fide Presentation Classification Error Rate (real users wrongly rejected)
- Pick the threshold row that matches your security needs

### Recognition Calibration Output Explained

```
People: 5 | genuine pairs: 45 | impostor pairs: 120
Genuine mean sim 0.620 | impostor mean sim 0.180
EER ~ 1.80% at threshold 0.430
Target FAR   threshold   resulting FRR
  1.00%       0.420       2.10%
  0.10%       0.480       5.30%
  0.01%       0.540      12.00%
```

- **FAR** = False Accept Rate (strangers wrongly identified as someone)
- **FRR** = False Reject Rate (enrolled users wrongly denied)
- More enrolled people and more images per person give more trustworthy numbers

---

## Future Improvements

### High Priority

| # | Improvement | Why It's Needed | Suggested Approach |
|---|---|---|---|
| 1 | **Database Migration to PostgreSQL** | SQLite doesn't support concurrent writes well — under heavy kiosk load with multiple devices, write contention can cause slowdowns | Replace SQLite with PostgreSQL or MySQL; use SQLAlchemy ORM for database abstraction |
| 2 | **Stronger Password Hashing** | SHA-256 is fast and vulnerable to brute-force attacks; not suitable for production credential storage | Switch to `bcrypt` or `argon2` with salting (use Python's `passlib` library) |
| 3 | **Multi-Camera / Multi-Kiosk Support** | Currently, the kiosk API endpoints don't enforce device-specific sessions for frame processing | Add kiosk device ID to frame processing, support multiple concurrent kiosk streams with device-level cooldown tracking |
| 4 | **HTTPS / TLS Encryption** | All traffic including base64 face frames is transmitted over plain HTTP | Deploy behind an NGINX reverse proxy with TLS certificates, or use uvicorn's `--ssl-keyfile` and `--ssl-certfile` options |
| 5 | **Role-Based Access Control (RBAC)** | Only one admin role exists; no department-level permissions or audit trails | Add admin roles (super-admin, department-admin, viewer), implement permission guards per endpoint |

### Medium Priority

| # | Improvement | Why It's Needed | Suggested Approach |
|---|---|---|---|
| 6 | **Face Embedding Encryption at Rest** | The `.npz` gallery file stores raw face embeddings — if stolen, these could theoretically be used for impersonation on other systems | Encrypt the gallery file using AES-256; decrypt in memory on startup using a master key |
| 7 | **Attendance Reports & Analytics Dashboard** | The admin can only view raw logs and export CSV — no visual analytics, trends, or department-level breakdowns | Add Chart.js or D3.js visualizations: daily/weekly attendance trends, department heatmaps, late-arrival patterns, individual attendance percentage |
| 8 | **Mask-Aware Recognition** | Post-COVID, users may wear partial face coverings that degrade recognition accuracy | Fine-tune ArcFace on masked-face datasets (e.g., MFR2) or integrate a periocular recognition module as fallback |
| 9 | **Docker Containerization** | Setup requires manual Python environment configuration and GPU driver setup | Create a `Dockerfile` with NVIDIA CUDA base image, `docker-compose.yml` for one-command deployment |
| 10 | **Mobile Admin App** | Admins must use a desktop browser to manage the system | Build a responsive PWA or React Native app with push notifications for anomalies |

### Low Priority / Research

| # | Improvement | Why It's Needed | Suggested Approach |
|---|---|---|---|
| 11 | **Federated Learning for Privacy** | Centralized face data storage raises privacy concerns in multi-branch deployments | Implement federated model updates where each branch trains locally and shares only model gradients, not raw face data |
| 12 | **Depth-Based Liveness (3D Camera)** | Passive liveness with RGB-only cameras can be defeated by high-quality 3D-printed masks | Integrate Intel RealSense or Azure Kinect depth cameras for depth-map-based liveness verification |
| 13 | **Continuous Model Retraining** | Anti-spoofing models may become less effective as new attack vectors emerge | Implement a feedback loop where rejected attempts are reviewed by admins and used to fine-tune the MiniFASNet models periodically |
| 14 | **Edge Deployment (Raspberry Pi / Jetson)** | Some deployments need standalone hardware without a PC server | Optimize models with TensorRT, quantize to INT8, and deploy on NVIDIA Jetson Nano/Orin |
| 15 | **Blockchain Attendance Ledger** | Attendance records could be tampered with if someone gains database access | Write attendance hashes to a permissioned blockchain (Hyperledger Fabric) for tamper-proof audit trails |
| 16 | **Multi-Factor Authentication** | Face-only authentication may not meet the highest security standards | Combine face recognition with RFID badge, fingerprint, or OTP as a second factor |
| 17 | **Cross-Platform Voice** | Windows SAPI limits deployment to Windows machines | Replace with `pyttsx3` (cross-platform) or Google Cloud TTS for platform-independent voice guidance |
| 18 | **WebSocket Real-Time Streaming** | Current polling-based frame processing (HTTP POST per frame) adds overhead | Replace frame submission with WebSocket streaming for lower latency and reduced HTTP overhead |

---

## License

This project is for educational and research purposes. The Silent-Face-Anti-Spoofing models are used under their original [Apache 2.0 License](Silent-Face-Anti-Spoofing/LICENSE).

---

<p align="center">
  <b>Built with ❤️ by <a href="https://github.com/SaiBhaskar05">SaiBhaskar05</a></b><br>
  ArcFace 512-d Embeddings • MiniFASNet Ensemble Anti-Spoofing • FastAPI Real-Time Engine
</p>
