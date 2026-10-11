/**
 * admin.js - Interactive Admin Console Controller
 */
let enrollStream = null;
let enrollTimer = null;
let capturedEnrollFrames = [];
const TARGET_ENROLL_FRAMES = 5;

// Toast Helper
function showToast(msg, type = "success") {
  const container = document.getElementById("toast-container") || createToastContainer();
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  
  let iconName = type === "success" ? "check-circle" : (type === "error" ? "alert-octagon" : "info");
  toast.innerHTML = `<i data-lucide="${iconName}" style="width:18px;"></i> <span>${msg}</span>`;
  container.appendChild(toast);
  lucide.createIcons();

  if (type === "success") window.sounds.playSuccess();
  if (type === "error") window.sounds.playError();

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(50px)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function createToastContainer() {
  const c = document.createElement("div");
  c.id = "toast-container";
  document.body.appendChild(c);
  return c;
}

// Tab Switching
function switchTab(tabId) {
  document.querySelectorAll(".nav-tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-tab") === tabId);
  });
  document.querySelectorAll(".tab-pane").forEach(pane => {
    pane.classList.toggle("active", pane.id === tabId);
  });

  if (tabId === "tab-enroll") {
    startEnrollCamera();
  } else {
    stopEnrollCamera();
  }

  if (tabId === "tab-attendance") {
    loadAttendanceLogs();
  }

  if (tabId === "tab-users") {
    loadUsersList();
  }

  if (tabId === "tab-overview") {
    refreshStats();
    loadRecentOverviewLogs();
  }
}

// -----------------------------------------------------------------------------
// Biometric Enrollment Studio
// -----------------------------------------------------------------------------
async function startEnrollCamera() {
  const video = document.getElementById("enrollVideo");
  if (!video) return;

  try {
    if (enrollStream) {
      enrollStream.getTracks().forEach(t => t.stop());
    }
    enrollStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      audio: false
    });
    video.srcObject = enrollStream;
    resetEnrollmentSession();
    startEnrollFrameLoop();
  } catch (err) {
    showToast("Webcam access denied or unavailable", "error");
    document.getElementById("enrollStatusText").textContent = "Camera Error";
  }
}

function stopEnrollCamera() {
  if (enrollStream) {
    enrollStream.getTracks().forEach(t => t.stop());
    enrollStream = null;
  }
  if (enrollTimer) {
    clearInterval(enrollTimer);
    enrollTimer = null;
  }
}

function resetEnrollmentSession() {
  capturedEnrollFrames = [];
  updateEnrollProgress();
  document.getElementById("enrollStatusText").textContent = "Position face in center";
  document.getElementById("enrollQualityBadge").textContent = "Waiting for face";
  document.getElementById("enrollQualityBadge").className = "hud-status-badge";
}

function updateEnrollProgress() {
  const count = capturedEnrollFrames.length;
  const pct = (count / TARGET_ENROLL_FRAMES) * 100;
  const bar = document.getElementById("enrollProgressFill");
  const text = document.getElementById("enrollSampleCountText");
  if (bar) bar.style.width = `${pct}%`;
  if (text) text.textContent = `${count} / ${TARGET_ENROLL_FRAMES} samples`;
}

let isEnrollInFlight = false;

function startEnrollFrameLoop() {
  if (enrollTimer) clearInterval(enrollTimer);
  const video = document.getElementById("enrollVideo");
  const canvas = document.getElementById("enrollCanvas");
  if (!video || !canvas) return;

  const ctx = canvas.getContext("2d");
  const offscreen = document.createElement("canvas");
  const offCtx = offscreen.getContext("2d");

  enrollTimer = setInterval(async () => {
    if (isEnrollInFlight || !video.videoWidth || capturedEnrollFrames.length >= TARGET_ENROLL_FRAMES) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const targetW = 400;
    const targetH = Math.round(video.videoHeight * (targetW / video.videoWidth));
    offscreen.width = targetW;
    offscreen.height = targetH;
    offCtx.drawImage(video, 0, 0, targetW, targetH);

    const b64 = offscreen.toDataURL("image/jpeg", 0.75);
    isEnrollInFlight = true;

    try {
      const res = await fetch("/api/kiosk/process-frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ frame: b64 })
      });
      const data = await res.json();

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const statusBadge = document.getElementById("enrollQualityBadge");
      const statusText = document.getElementById("enrollStatusText");

      if (!data.has_face) {
        statusBadge.textContent = "No Face Detected";
        statusBadge.className = "hud-status-badge";
        statusText.textContent = "Position face in camera view";
        return;
      }

      // Draw bounding box
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
        ctx.fillStyle = data.usable ? "#10b981" : "#f59e0b";
        const len = 14;
        ctx.fillRect(mirrorX - 2, scaledY - 2, len, 4);
        ctx.fillRect(mirrorX - 2, scaledY - 2, 4, len);
        ctx.fillRect(mirrorX + scaledW - len + 2, scaledY - 2, len, 4);
        ctx.fillRect(mirrorX + scaledW - 2, scaledY - 2, 4, len);
        ctx.restore();
      }

      if (data.usable && data.is_frontal) {
        statusBadge.textContent = "Face Position OK";
        statusBadge.className = "hud-status-badge badge-present";
        statusText.textContent = "Capturing biometric samples...";

        // Collect sample
        if (capturedEnrollFrames.length < TARGET_ENROLL_FRAMES) {
          capturedEnrollFrames.push(b64);
          window.sounds.playSnap();
          updateEnrollProgress();

          if (capturedEnrollFrames.length === TARGET_ENROLL_FRAMES) {
            statusText.textContent = "Sample collection complete! Ready to submit.";
            window.sounds.playSuccess();
          }
        }
      } else {
        statusBadge.textContent = data.reason || "Adjust Face";
        statusBadge.className = "hud-status-badge badge-late";
        statusText.textContent = data.reason || "Center and look directly at the camera";
      }

    } catch (e) {
      console.warn("Enroll frame processing:", e);
    } finally {
      isEnrollInFlight = false;
    }
  }, 120);
}

// Handle Enrollment Form Submission
async function handleEnrollSubmit(e) {
  e.preventDefault();
  const empId = document.getElementById("enrollEmpId").value.trim();
  const name = document.getElementById("enrollName").value.trim();
  const dept = document.getElementById("enrollDept").value.trim();
  const email = document.getElementById("enrollEmail").value.trim();
  const phone = document.getElementById("enrollPhone").value.trim();
  const submitBtn = document.getElementById("enrollSubmitBtn");

  if (!capturedEnrollFrames || capturedEnrollFrames.length < 2) {
    showToast("Please position face to capture at least 2 clear biometric samples first.", "warning");
    return;
  }

  submitBtn.disabled = true;
  submitBtn.innerHTML = `<i data-lucide="loader" class="spin" style="width:16px;"></i> Registering Biometrics...`;
  lucide.createIcons();

  try {
    const res = await fetch("/api/admin/enroll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        employee_id: empId,
        name: name,
        department: dept,
        email: email,
        phone: phone,
        frames: capturedEnrollFrames
      })
    });

    const data = await res.json();
    if (data.success) {
      showToast(data.message, "success");
      document.getElementById("enrollUserForm").reset();
      resetEnrollmentSession();
      refreshStats();
    } else {
      showToast(data.message || "Enrollment failed", "error");
    }
  } catch (err) {
    showToast("Error connecting to server", "error");
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `<span>Complete Biometric Registration</span> <i data-lucide="check" style="width:16px;"></i>`;
    lucide.createIcons();
  }
}

// -----------------------------------------------------------------------------
// User Management List & Deletion with Live Search
// -----------------------------------------------------------------------------
let cachedUsers = [];

async function loadUsersList() {
  const tbody = document.getElementById("usersTableBody");
  if (!tbody) return;

  try {
    const res = await fetch("/api/admin/users");
    const data = await res.json();
    if (!data.success) return;

    cachedUsers = data.users || [];
    renderUsersTable(cachedUsers);
  } catch (err) {
    console.error("Error loading users:", err);
  }
}

function renderUsersTable(users) {
  const tbody = document.getElementById("usersTableBody");
  if (!tbody) return;

  if (users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 32px; color: var(--text-muted);">No users match the search criteria.</td></tr>`;
    return;
  }

  tbody.innerHTML = users.map(u => `
    <tr>
      <td>
        <div class="user-avatar-cell">
          <img src="${u.avatar_path || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=100'}" class="avatar-img" alt="Avatar">
          <div>
            <div style="font-weight: 700; color: var(--text-main);">${u.name}</div>
            <div style="font-size: 0.8rem; color: var(--text-muted);">${u.email || 'No email registered'}</div>
          </div>
        </div>
      </td>
      <td><span style="font-family: var(--font-mono); color: var(--primary); font-weight:600;">${u.employee_id}</span></td>
      <td>${u.department}</td>
      <td><span class="badge badge-active">${u.sample_count} Embeddings</span></td>
      <td style="color: var(--text-muted); font-size: 0.85rem;">${u.created_at || 'Just now'}</td>
      <td>
        <button class="btn btn-secondary" style="padding: 6px 12px; color: var(--danger);" onclick="deleteUserPrompt('${u.employee_id}', '${u.name}')" title="Delete Profile">
          <i data-lucide="trash-2" style="width: 14px;"></i>
        </button>
      </td>
    </tr>
  `).join("");
  lucide.createIcons();
}

function filterUsersList() {
  const query = (document.getElementById("userSearchInput")?.value || "").toLowerCase().trim();
  if (!query) {
    renderUsersTable(cachedUsers);
    return;
  }
  const filtered = cachedUsers.filter(u => 
    (u.name && u.name.toLowerCase().includes(query)) ||
    (u.employee_id && u.employee_id.toLowerCase().includes(query)) ||
    (u.department && u.department.toLowerCase().includes(query))
  );
  renderUsersTable(filtered);
}

async function deleteUserPrompt(empId, name) {
  if (!confirm(`Are you sure you want to remove staff member '${name}' (${empId}) and delete all stored face embeddings from the biometric gallery?`)) {
    return;
  }

  try {
    const res = await fetch(`/api/admin/users/${empId}`, { method: "DELETE" });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, "success");
      loadUsersList();
      refreshStats();
    } else {
      showToast(data.message || "Failed to delete user", "error");
    }
  } catch (err) {
    showToast("Server error deleting user", "error");
  }
}

// -----------------------------------------------------------------------------
// Attendance Logs & Export with Live Search
// -----------------------------------------------------------------------------
let cachedAttendanceLogs = [];

async function loadAttendanceLogs() {
  const tbody = document.getElementById("attendanceTableBody");
  if (!tbody) return;

  try {
    const res = await fetch("/api/admin/attendance");
    const data = await res.json();
    if (!data.success) return;

    cachedAttendanceLogs = data.logs || [];
    renderAttendanceTable(cachedAttendanceLogs);
  } catch (err) {
    console.error("Error loading logs:", err);
  }
}

function renderAttendanceTable(logs) {
  const tbody = document.getElementById("attendanceTableBody");
  if (!tbody) return;

  if (logs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 32px; color: var(--text-muted);">No attendance records found.</td></tr>`;
    return;
  }

  tbody.innerHTML = logs.map(log => `
    <tr>
      <td>
        <div style="font-weight: 700; color: var(--text-main);">${log.user_name}</div>
        <div style="font-size: 0.78rem; font-family: var(--font-mono); color: var(--text-dim);">${log.employee_id}</div>
      </td>
      <td>${log.department}</td>
      <td><span style="font-family: var(--font-mono); font-size: 0.88rem;">${log.date_str}</span></td>
      <td><span style="font-weight: 600; color: var(--cyan); font-family: var(--font-mono);">${log.time_str}</span></td>
      <td>
        <span class="badge ${log.status === 'Present' ? 'badge-present' : 'badge-late'}">
          ${log.status}
        </span>
      </td>
      <td>
        <span style="font-size: 0.85rem; color: #059669; font-weight: 700;">${(log.similarity_score * 100).toFixed(1)}% Match</span>
        <div style="font-size: 0.75rem; color: var(--text-dim);">PAD Score: ${(log.anti_spoof_score * 100).toFixed(0)}%</div>
      </td>
      <td>
        <span style="font-size: 0.82rem; color: var(--text-muted);">${log.device_name}</span>
      </td>
    </tr>
  `).join("");
  lucide.createIcons();
}

function filterAttendanceLogs() {
  const query = (document.getElementById("attendanceSearchInput")?.value || "").toLowerCase().trim();
  if (!query) {
    renderAttendanceTable(cachedAttendanceLogs);
    return;
  }
  const filtered = cachedAttendanceLogs.filter(log => 
    (log.user_name && log.user_name.toLowerCase().includes(query)) ||
    (log.employee_id && log.employee_id.toLowerCase().includes(query)) ||
    (log.department && log.department.toLowerCase().includes(query))
  );
  renderAttendanceTable(filtered);
}

// -----------------------------------------------------------------------------
// Overview Tab: Live Attendance Stream
// -----------------------------------------------------------------------------
async function loadRecentOverviewLogs() {
  const tbody = document.getElementById("overviewRecentLogs");
  if (!tbody) return;

  try {
    const res = await fetch("/api/admin/attendance?limit=6");
    const data = await res.json();
    if (!data.success) return;

    const logs = data.logs || [];
    if (logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding: 24px; color: var(--text-muted);">No attendance verifications logged today yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = logs.slice(0, 6).map(log => `
      <tr>
        <td>
          <div style="font-weight: 700; color: var(--text-main); font-size: 0.9rem;">${log.user_name}</div>
          <div style="font-size: 0.75rem; font-family: var(--font-mono); color: var(--text-dim);">${log.employee_id} • ${log.department}</div>
        </td>
        <td>
          <span style="font-weight: 600; color: var(--cyan); font-family: var(--font-mono); font-size: 0.85rem;">${log.time_str}</span>
        </td>
        <td>
          <span class="badge ${log.status === 'Present' ? 'badge-present' : 'badge-late'}" style="font-size: 0.72rem; padding: 3px 8px;">
            ${log.status}
          </span>
        </td>
        <td>
          <span style="font-size: 0.82rem; color: #059669; font-weight: 700;">${(log.similarity_score * 100).toFixed(0)}%</span>
          <span style="font-size: 0.72rem; color: var(--text-dim); margin-left: 4px;">(PAD ${(log.anti_spoof_score * 100).toFixed(0)}%)</span>
        </td>
      </tr>
    `).join("");
    lucide.createIcons();
  } catch (err) {
    console.warn("Could not load recent overview logs:", err);
  }
}

// -----------------------------------------------------------------------------
// Stats & Settings
// -----------------------------------------------------------------------------
async function refreshStats() {
  try {
    const res = await fetch("/api/admin/stats");
    const data = await res.json();
    if (data.success) {
      const s = data.stats;
      document.getElementById("statTotalUsers").textContent = s.total_users;
      document.getElementById("statTodayPresent").textContent = s.today_present;
      document.getElementById("statTodayLate").textContent = s.today_late;
      document.getElementById("statAttendanceRate").textContent = s.attendance_rate;
    }
  } catch (e) {}
}

async function handleSettingsSubmit(e) {
  e.preventDefault();
  const payload = {
    match_thresh: document.getElementById("cfgMatchThresh").value,
    margin: document.getElementById("cfgMargin").value,
    live_score_thresh: document.getElementById("cfgLiveScoreThresh").value,
    cooldown_minutes: document.getElementById("cfgCooldown").value,
    late_cutoff_time: document.getElementById("cfgLateTime").value
  };

  try {
    const res = await fetch("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast("Security & System Settings saved successfully!", "success");
    }
  } catch (err) {
    showToast("Failed to save settings", "error");
  }
}

// Document Ready Initialization
document.addEventListener("DOMContentLoaded", () => {
  lucide.createIcons();
  refreshStats();
  loadRecentOverviewLogs();

  const enrollForm = document.getElementById("enrollUserForm");
  if (enrollForm) enrollForm.addEventListener("submit", handleEnrollSubmit);

  const settingsForm = document.getElementById("settingsForm");
  if (settingsForm) settingsForm.addEventListener("submit", handleSettingsSubmit);
});
