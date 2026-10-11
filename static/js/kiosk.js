/**
 * kiosk.js - Ultra-Fast 24/7 Continuous Biometric Attendance Kiosk Controller
 * Optimized for low-latency streaming and instant attendance verification.
 */
let kioskStream = null;
let isFrameInFlight = false;
let isVerifying = false;
let lastVerifyTimestamp = 0;
let consecutiveFrontalFrames = 0;
const VERIFY_COOLDOWN_MS = 2500; // UI pause after a successful or failed scan

// Update Live Digital Clock
function updateClock() {
  const clockEl = document.getElementById("kioskClock");
  const dateEl = document.getElementById("kioskDate");
  if (!clockEl || !dateEl) return;

  const now = new Date();
  clockEl.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  dateEl.textContent = now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
}
setInterval(updateClock, 1000);

// Initialize Webcam
async function startKioskCamera() {
  const video = document.getElementById("kioskVideo");
  if (!video) return;

  try {
    kioskStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      audio: false
    });
    video.srcObject = kioskStream;
    startFastKioskLoop();
    loadTodayAttendanceFeed();
  } catch (err) {
    document.getElementById("instructionText").textContent = "Camera Error: Please allow camera access";
    console.error("Camera access error:", err);
  }
}

// Continuous Low-Latency Tracking Loop
function startFastKioskLoop() {
  const video = document.getElementById("kioskVideo");
  const canvas = document.getElementById("kioskCanvas");
  if (!video || !canvas) return;

  const ctx = canvas.getContext("2d");
  const offscreen = document.createElement("canvas");
  const offCtx = offscreen.getContext("2d");

  // Run at a crisp 10 FPS (100ms) with in-flight lock to avoid network queueing
  setInterval(async () => {
    if (isVerifying || isFrameInFlight || !video.videoWidth) return;
    if (Date.now() - lastVerifyTimestamp < VERIFY_COOLDOWN_MS) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    // Fast Downscale for inference (400px width keeps base64 payload tiny and fast)
    const targetW = 400;
    const targetH = Math.round(video.videoHeight * (targetW / video.videoWidth));
    offscreen.width = targetW;
    offscreen.height = targetH;
    offCtx.drawImage(video, 0, 0, targetW, targetH);

    const b64 = offscreen.toDataURL("image/jpeg", 0.75);
    isFrameInFlight = true;

    try {
      const res = await fetch("/api/kiosk/process-frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ frame: b64 })
      });
      const data = await res.json();

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const banner = document.getElementById("instructionText");
      const target = document.getElementById("centerTarget");

      if (!data.has_face) {
        consecutiveFrontalFrames = 0;
        target.classList.remove("active");
        banner.textContent = "Please Look at the Camera";
        return;
      }

      // Scale box coordinates from 400px back to canvas display size
      const scaleFactor = video.videoWidth / targetW;
      const box = data.box;
      if (box) {
        ctx.save();
        const scaledX = box.x * scaleFactor;
        const scaledY = box.y * scaleFactor;
        const scaledW = box.w * scaleFactor;
        const scaledH = box.h * scaleFactor;

        const mirrorX = canvas.width - (scaledX + scaledW);
        ctx.strokeStyle = data.usable ? "#10b981" : "#f59e0b";
        ctx.lineWidth = 3;
        ctx.strokeRect(mirrorX, scaledY, scaledW, scaledH);

        // Corner accents
        const len = 20;
        ctx.fillStyle = ctx.strokeStyle;
        ctx.fillRect(mirrorX - 2, scaledY - 2, len, 4);
        ctx.fillRect(mirrorX - 2, scaledY - 2, 4, len);
        ctx.fillRect(mirrorX + scaledW - len + 2, scaledY - 2, len, 4);
        ctx.fillRect(mirrorX + scaledW - 2, scaledY - 2, 4, len);
        ctx.restore();
      }

      if (data.usable && data.is_frontal) {
        consecutiveFrontalFrames++;
        target.classList.add("active");
        banner.textContent = "Verifying Identity...";

        // Trigger instantaneous verification on 2 steady frontal frames
        if (consecutiveFrontalFrames >= 2) {
          consecutiveFrontalFrames = 0;
          triggerInstantVerification(b64);
        }
      } else {
        consecutiveFrontalFrames = 0;
        target.classList.remove("active");
        banner.textContent = data.reason || "Center your face in camera";
      }

    } catch (e) {
      console.warn("Frame loop warning:", e);
    } finally {
      isFrameInFlight = false;
    }
  }, 100);
}

// Instant Verification Call (<150ms execution)
async function triggerInstantVerification(frameB64) {
  isVerifying = true;
  const resultCard = document.getElementById("matchResultCard");
  const deviceName = document.body.getAttribute("data-device-name") || "Main Kiosk";

  try {
    const res = await fetch("/api/kiosk/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frames: [frameB64], device_name: deviceName })
    });
    const data = await res.json();
    lastVerifyTimestamp = Date.now();

    if (data.success) {
      // Verified match
      window.sounds.playSuccess();
      window.sounds.speak(data.already_marked ? `Welcome back ${data.name}` : `Welcome ${data.name}`);

      document.getElementById("matchAvatar").src = data.avatar || "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=120";
      document.getElementById("matchName").textContent = data.name;
      document.getElementById("matchEmpId").textContent = data.employee_id || "ID: Verified";
      document.getElementById("matchDept").textContent = data.department || "General";
      document.getElementById("matchStatusBadge").textContent = data.already_marked ? "ALREADY RECORDED" : data.status.toUpperCase();
      document.getElementById("matchStatusBadge").className = `badge ${data.already_marked ? 'badge-active' : (data.status === 'Present' ? 'badge-present' : 'badge-late')}`;
      document.getElementById("matchScoreText").textContent = `Match: ${(data.score * 100).toFixed(0)}% • PAD Real: ${(data.anti_spoof_score * 100).toFixed(0)}%`;

      resultCard.style.borderColor = "#10b981";
      resultCard.classList.add("show");

      if (!data.already_marked) {
        addLogToLiveFeed(data);
      }

      setTimeout(() => {
        resultCard.classList.remove("show");
        isVerifying = false;
      }, 2200);

    } else {
      // Spoof or access denied
      window.sounds.playError();
      window.sounds.speak(data.is_spoof ? "Spoof Detected" : "Access Denied");

      document.getElementById("matchAvatar").src = "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=120";
      document.getElementById("matchName").textContent = data.is_spoof ? "SPOOF DETECTED" : "UNRECOGNIZED FACE";
      document.getElementById("matchEmpId").textContent = data.message || "Access Denied";
      document.getElementById("matchDept").textContent = "Security Alert";
      document.getElementById("matchStatusBadge").textContent = "REJECTED";
      document.getElementById("matchStatusBadge").className = "badge badge-spoof";
      document.getElementById("matchScoreText").textContent = data.anti_spoof_score ? `PAD Liveness: ${(data.anti_spoof_score * 100).toFixed(0)}%` : "Not Enrolled";

      resultCard.style.borderColor = "#ef4444";
      resultCard.classList.add("show");

      setTimeout(() => {
        resultCard.classList.remove("show");
        isVerifying = false;
      }, 2000);
    }

  } catch (err) {
    console.error("Verification error:", err);
    isVerifying = false;
  }
}

// Load and Render Today's Attendance Feed
async function loadTodayAttendanceFeed() {
  const container = document.getElementById("kioskFeedList");
  if (!container) return;

  try {
    const res = await fetch("/api/kiosk/today-logs");
    const data = await res.json();
    if (!data.success) return;

    document.getElementById("todayAttendeeCount").textContent = data.logs.length;

    if (data.logs.length === 0) {
      container.innerHTML = `<div style="text-align:center; padding: 24px; color: var(--text-dim); font-size: 0.85rem;">No attendances recorded yet today. Stand in front of camera to verify.</div>`;
      return;
    }

    container.innerHTML = data.logs.map(log => `
      <div class="kiosk-feed-item">
        <img src="${log.avatar_path || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=80'}" style="width:38px; height:38px; border-radius:50%; object-fit:cover; border:1.5px solid var(--border);">
        <div style="flex:1; overflow:hidden;">
          <div style="font-weight:800; font-size:0.88rem; color: var(--text-heading); white-space:nowrap; text-overflow:ellipsis; overflow:hidden;">${log.user_name}</div>
          <div style="font-size:0.75rem; color:var(--text-muted); font-weight:500;">${log.department}</div>
        </div>
        <div style="text-align:right;">
          <div style="font-family:var(--font-mono); font-size:0.82rem; font-weight:700; color:var(--primary);">${log.time_str}</div>
          <span class="badge ${log.status === 'Present' ? 'badge-present' : 'badge-late'}" style="font-size:0.68rem; padding: 2px 7px;">${log.status}</span>
        </div>
      </div>
    `).join("");

  } catch (err) {
    console.error("Error loading kiosk feed:", err);
  }
}

function addLogToLiveFeed(log) {
  const container = document.getElementById("kioskFeedList");
  if (!container) return;

  const countEl = document.getElementById("todayAttendeeCount");
  if (countEl) countEl.textContent = parseInt(countEl.textContent || "0") + 1;

  const item = document.createElement("div");
  item.className = "kiosk-feed-item";
  item.innerHTML = `
    <img src="${log.avatar || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=80'}" style="width:38px; height:38px; border-radius:50%; object-fit:cover; border:1.5px solid var(--border);">
    <div style="flex:1; overflow:hidden;">
      <div style="font-weight:800; font-size:0.88rem; color: var(--text-heading); white-space:nowrap; text-overflow:ellipsis; overflow:hidden;">${log.name}</div>
      <div style="font-size:0.75rem; color:var(--text-muted); font-weight:500;">${log.department}</div>
    </div>
    <div style="text-align:right;">
      <div style="font-family:var(--font-mono); font-size:0.82rem; font-weight:700; color:var(--primary);">${log.time}</div>
      <span class="badge ${log.status === 'Present' ? 'badge-present' : 'badge-late'}" style="font-size:0.68rem; padding: 2px 7px;">${log.status}</span>
    </div>
  `;
  container.prepend(item);
}

// Fullscreen Toggle
function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen().catch(() => {});
  }
}

document.addEventListener("DOMContentLoaded", () => {
  lucide.createIcons();
  updateClock();
  startKioskCamera();
});
