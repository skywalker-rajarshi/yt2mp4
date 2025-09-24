// --- API URL Configuration ---
const API_BASE_URL = "https://yt-downloader-api-isf5.onrender.com/"; // REPLACE THIS with your actual Render URL

// --- DOM Elements ---
const getElem = (id) => document.getElementById(id);
const form = getElem("form");
const urlInput = getElem("url");
const formatSel = getElem("format");
const qualityWrap = getElem("qualityWrap");
const qualitySel = getElem("quality");
const bitrateWrap = getElem("bitrateWrap");
const bitrateSel = getElem("bitrate");
const termsCheck = getElem("terms");
const submitBtn = getElem("submitBtn");
const statusBox = getElem("status");

// Video Info Elements
const videoInfoSection = getElem("videoInfo");
const thumbnailImg = getElem("thumbnail");
const videoTitleElem = getElem("videoTitle");
const estimatedSizeElem = getElem("estimatedSize");
const downloadBtn = getElem("downloadBtn");
const downloadProgressWrap = getElem("downloadProgressWrap");
const downloadProgress = getElem("downloadProgress");

// --- State Management ---
let currentVideoInfo = {};
let progressIntervalId = null;

// --- UI Functions ---
function setStatus(msg, cls) {
  statusBox.className = "status " + (cls || "");
  statusBox.textContent = msg || "";
}

function syncFields() {
  const isAudio = formatSel.value === "mp3";
  qualityWrap.style.display = isAudio ? "none" : "";
  bitrateWrap.style.display = isAudio ? "" : "none";
}

function updateSubmitButton() {
  submitBtn.disabled = !termsCheck.checked || !urlInput.value.trim();
}

// --- Progress Bar Functions (Rewritten for clarity and correctness) ---
function startProgress() {
  if (progressIntervalId) clearInterval(progressIntervalId);
  downloadProgressWrap.style.display = "block";
  let width = 5;
  downloadProgress.style.width = width + "%";
  progressIntervalId = setInterval(() => {
    width += Math.random() * 8;
    if (width >= 95) {
      width = 95;
      clearInterval(progressIntervalId);
    }
    downloadProgress.style.width = width + "%";
  }, 500);
}

function stopProgress() {
  if (progressIntervalId) clearInterval(progressIntervalId);
}

function completeProgress() {
  stopProgress();
  if (downloadProgressWrap.style.display === "block") {
    downloadProgress.style.width = "100%";
  }
}

function hideProgress() {
  stopProgress();
  downloadProgressWrap.style.display = "none";
  downloadProgress.style.width = "0%";
}

// --- API & Event Handlers ---
async function postJSON(url, data) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const txt = await res.text();
    let errorMsg = "Request failed.";
    try {
      const jsonError = JSON.parse(txt);
      errorMsg = jsonError.detail || errorMsg;
    } catch (e) {
      errorMsg = txt || errorMsg;
    }
    throw new Error(errorMsg);
  }
  return res.json();
}

async function handleFetchDetails(e) {
  e.preventDefault();
  setStatus("Fetching details...", "");
  videoInfoSection.style.display = "none";
  hideProgress();
  submitBtn.disabled = true;

  try {
    const payload = {
      url: urlInput.value.trim(),
      format: formatSel.value,
      quality: qualitySel.value,
    };

    const data = await postJSON(`${API_BASE_URL}/api/video_info`, payload);

    currentVideoInfo = payload; // Store for download
    videoTitleElem.textContent = data.title;
    thumbnailImg.src = data.thumbnail_url;
    thumbnailImg.alt = `Thumbnail for ${data.title}`;
    estimatedSizeElem.textContent = `Estimated size: ${data.estimated_size}`;
    videoInfoSection.style.display = "flex";
    setStatus("Details loaded.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    updateSubmitButton();
  }
}

async function handleDownload() {
  setStatus("Download has started", "");
  downloadBtn.disabled = true;
  startProgress();

  try {
    const payload = {
      ...currentVideoInfo,
      bitrate: bitrateSel.value,
    };
    const response = await fetch(`${API_BASE_URL}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const txt = await response.text();
      throw new Error(txt || "Download failed");
    }

    completeProgress();

    const blob = await response.blob();
    const header = response.headers.get("Content-Disposition");
    const match = header && header.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : "download";

    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(link.href);
    setStatus("Download has been completed!", "ok");
  } catch (err) {
    setStatus(err.message, "error");
    hideProgress();
  } finally {
    downloadBtn.disabled = false;
  }
}

// --- Theme Toggle ---
const root = document.documentElement;
const themeToggle = getElem("themeToggle");
const iconMoon = getElem("iconMoon");
const iconSun = getElem("iconSun");

function updateIcons() {
  const isDark = root.getAttribute("data-theme") === "dark";
  iconSun.style.display = isDark ? "" : "none";
  iconMoon.style.display = isDark ? "none" : "";
}

function initTheme() {
  const storedTheme = localStorage.getItem("theme");
  if (storedTheme) {
    root.setAttribute("data-theme", storedTheme);
  } else {
    root.setAttribute("data-theme", "light"); // Default to light
  }
  updateIcons();
}

themeToggle.addEventListener("click", () => {
  const isDark = root.getAttribute("data-theme") === "dark";
  const newTheme = isDark ? "light" : "dark";
  root.setAttribute("data-theme", newTheme);
  localStorage.setItem("theme", newTheme);
  updateIcons();
});

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  getElem("year").textContent = new Date().getFullYear();
  initTheme();

  // Event Listeners
  formatSel.addEventListener("change", syncFields);
  termsCheck.addEventListener("change", updateSubmitButton);
  urlInput.addEventListener("input", updateSubmitButton);
  form.addEventListener("submit", handleFetchDetails);
  downloadBtn.addEventListener("click", handleDownload);

  // Initial state setup
  syncFields();
  updateSubmitButton();
});
