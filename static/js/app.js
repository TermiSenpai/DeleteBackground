// DeleteBackground — vanilla ES2020 frontend. No build step.
"use strict";

/* ============================================================ */
/* Helpers                                                       */
/* ============================================================ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

function formatNumber(n) {
  return Number(n ?? 0).toLocaleString();
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m < 60) return `${m}m ${String(s).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, "0")}m`;
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}

function formatRelative(unixSeconds) {
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - unixSeconds);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function clampInt(raw, min, max, fallback) {
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

/* ============================================================ */
/* Constants                                                     */
/* ============================================================ */

const QUALITY_TO_MODEL = {
  fast: "u2netp",
  balanced: "isnet-general-use",
  high: "birefnet-general",
};

const MODEL_QUALITY_TO_PRESET = {
  fast: "fast",
  balanced: "balanced",
  high: "high",
  premium: "high",
};

const SCREENS = {
  dashboard: { title: "Batches", subtitle: "Remove backgrounds from a folder of images, locally." },
  live: { title: "Live processing", subtitle: "Live status of the running job." },
  output: { title: "Output folder", subtitle: "Browse PNGs that have been produced." },
  settings: { title: "Settings", subtitle: "Persisted to settings.json in the project root." },
  logs: { title: "Logs", subtitle: "Recent events from this session." },
};

/* ============================================================ */
/* Element registry                                              */
/* ============================================================ */

const els = {
  navItems: $$(".nav-item[data-screen]"),
  statusPill: $("#status-pill"),
  statusPillTitle: $("#status-pill-title"),
  statusPillSub: $("#status-pill-sub"),
  connBadge: $("#conn-badge"),
  screenTitle: $("#screen-title"),
  screenSubtitle: $("#screen-subtitle"),
  viewports: $$(".screen__viewport[data-screen]"),

  dropzone: $("#dropzone"),
  folderPicker: $("#folder-picker"),
  inputFolder: $("#input-folder"),
  outputFolder: $("#output-folder"),
  modelSelect: $("#model-select"),
  modelHint: $("#model-hint"),
  qualityButtons: $$(".segmented [data-quality]"),
  workers: $("#workers"),
  workersValue: $("#workers-value"),
  skipExisting: $("#skip-existing"),
  force: $("#force"),
  recursive: $("#recursive"),
  startBtn: $("#start-btn"),
  cancelBtn: $("#cancel-btn"),
  liveCancelBtn: $("#live-cancel-btn"),
  chooseFolderBtn: $("#choose-folder-btn"),
  exportCsvBtn: $("#export-csv-btn"),

  queueBody: $("#queue-body"),
  queueEmpty: $("#queue-empty"),
  queueCount: $("#queue-count"),

  statTotalPretty: $("#stat-total-pretty"),
  statTotalHint: $("#stat-total-hint"),
  statTimeSaved: $("#stat-time-saved"),
  statFailures: $("#stat-failures"),
  statFailuresHint: $("#stat-failures-hint"),
  previewHint: $("#preview-hint"),

  stateBadge: $("#state-badge"),
  heroProcessed: $("#hero-processed"),
  heroTotal: $("#hero-total"),
  heroSub: $("#hero-sub"),
  progressFill: $("#progress-fill"),
  statProcessed: $("#stat-processed"),
  statSkipped: $("#stat-skipped"),
  statFailed: $("#stat-failed"),
  statPercent: $("#stat-percent"),
  statThroughput: $("#stat-throughput"),
  statEta: $("#stat-eta"),
  statEtaHint: $("#stat-eta-hint"),
  thumbs: $("#thumbs"),
  thumbsEmpty: $("#thumbs-empty"),
  resultFilters: $$(".segmented--small [data-filter]"),

  outputGrid: $("#output-grid"),
  outputEmpty: $("#output-empty"),
  outputFolderLabel: $("#output-folder-label"),
  outputRefreshBtn: $("#output-refresh-btn"),

  alphaMatting: $("#alpha-matting"),
  amFg: $("#am-fg"),
  amBg: $("#am-bg"),
  amErode: $("#am-erode"),
  pngCompression: $("#png-compression"),
  backgroundColor: $("#background-color"),
  backgroundColorPicker: $("#background-color-picker"),

  logs: $("#logs"),
  logsEmpty: $("#logs-empty"),
  logsClearBtn: $("#logs-clear-btn"),
  logsCopyBtn: $("#logs-copy-btn"),
  logFilterButtons: $$("[data-log-filter]"),

  toast: $("#toast"),

  loaderModal: $("#loader-modal"),
  loaderModelName: $("#loader-model-name"),
  loaderElapsed: $("#loader-elapsed"),

  lightbox: $("#lightbox"),
  lightboxImg: $("#lightbox-img"),
  lightboxTitle: $("#lightbox-title"),
  lightboxSub: $("#lightbox-sub"),
  lightboxCounter: $("#lightbox-counter"),
  lightboxDownload: $("#lightbox-download"),
  lightboxPrev: $("#lightbox-prev"),
  lightboxNext: $("#lightbox-next"),
};

/* ============================================================ */
/* State                                                         */
/* ============================================================ */

const state = {
  preferences: null,
  models: [],
  defaultModel: "isnet-general-use",
  socket: null,
  reconnectTimer: null,
  reconnectDelay: 1500,
  saveTimer: null,
  toastTimer: null,
  workersLocal: 4,
  resultFilter: "all",
  /** @type {Map<string, { name: string, status: string, model: string, durationSec?: number }>} */
  records: new Map(),
  prevState: "idle",
  prevCounts: { processed: 0, skipped: 0, failed: 0 },
  lastStatus: null,
  loaderActive: false,
  loaderStartedAt: 0,
  loaderTimer: null,

  /** @type {Array<{ src: string, name: string, sub: string }>} */
  outputItems: [],
  /** Currently-open lightbox group + index. */
  lightbox: { items: [], index: -1, lastFocus: null },

  /** Activity-log buffer. Newest entries are pushed to the end; the UI
      renders them in reverse. Counts are kept in sync with the buffer so
      filter chips never need to recount the full list. */
  logs: {
    /** @type {Array<{ id: number, level: "info"|"ok"|"warn"|"err", source: string, message: string, details: Record<string, unknown> | null, time: Date }>} */
    entries: [],
    filter: "all",
    counts: { info: 0, ok: 0, warn: 0, err: 0 },
    nextId: 1,
  },

  /** Tracks WebSocket lifecycle so connect/disconnect logs don't spam on
      reconnect storms. We log the first close after an open, and the
      reconnect that follows — not the initial connect or repeated retries. */
  wsState: "init",

  /** Last value of status.last_error we logged. The server keeps last_error
      in every status payload, so without dedup we'd log it on every WS tick. */
  lastJobError: "",
};

/* ============================================================ */
/* REST                                                          */
/* ============================================================ */

async function api(path, options = {}) {
  // Default to a 30s ceiling so a stalled server surfaces as a real error
  // in the UI instead of leaving status indicators stuck on "Checking…".
  // Caller can pass `timeoutMs: 0` to opt out (e.g. long-running uploads).
  const { timeoutMs = 30000, signal: callerSignal, ...rest } = options;
  const controller = new AbortController();
  const timer = timeoutMs > 0
    ? setTimeout(() => controller.abort(new Error("Request timed out.")), timeoutMs)
    : null;
  if (callerSignal) {
    if (callerSignal.aborted) controller.abort(callerSignal.reason);
    else callerSignal.addEventListener("abort", () => controller.abort(callerSignal.reason), { once: true });
  }
  try {
    const res = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json", ...(rest.headers ?? {}) },
      signal: controller.signal,
      ...rest,
    });
    const ct = res.headers.get("content-type") ?? "";
    const body = ct.includes("application/json") ? await res.json() : null;
    if (!res.ok) {
      const detail = body?.detail ?? res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return body;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(controller.signal.reason?.message || "Request timed out.");
    }
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/* ============================================================ */
/* Bootstrap                                                     */
/* ============================================================ */

async function bootstrap() {
  try {
    const [{ preferences }, modelsResp] = await Promise.all([
      api("/preferences"),
      api("/models"),
    ]);
    state.preferences = preferences;
    state.models = modelsResp.models;
    state.defaultModel = modelsResp.default;
    state.workersLocal = readLocalWorkers();

    renderModelSelect();
    hydrateForm();
    syncQualityFromModel(state.preferences.model_name);
    updateWorkersDisplay();
    connectWebSocket();

    const initial = await api("/job");
    applyStatus(initial);
    appendLog("ok", "Ready", {
      source: "system",
      details: {
        models: state.models.length,
        default: state.defaultModel,
      },
    });
  } catch (err) {
    console.error("Bootstrap failed", err);
    toast(`Failed to initialise: ${err.message}`, "err");
    appendLog("err", "Initialisation failed", {
      source: "system",
      details: { error: err.message },
    });
  }
}

function readLocalWorkers() {
  const raw = localStorage.getItem("dbg.workers");
  const n = Number.parseInt(raw ?? "", 10);
  return Number.isFinite(n) && n >= 1 && n <= 8 ? n : 4;
}

function renderModelSelect() {
  const groups = [
    { quality: "premium", label: "Premium quality" },
    { quality: "high", label: "High quality" },
    { quality: "balanced", label: "Balanced" },
    { quality: "fast", label: "Fast" },
  ];
  const fragments = [];
  for (const g of groups) {
    const items = state.models.filter((m) => m.quality === g.quality);
    if (!items.length) continue;
    fragments.push(`<optgroup label="${escapeHtml(g.label)}">`);
    for (const m of items) {
      const sel = m.id === state.preferences.model_name ? " selected" : "";
      fragments.push(`<option value="${m.id}"${sel}>${escapeHtml(m.label)}</option>`);
    }
    fragments.push("</optgroup>");
  }
  els.modelSelect.innerHTML = fragments.join("");
  updateModelHint();
}

/* ============================================================ */
/* Custom combobox — replaces the native <select> popup so the   */
/* dropdown matches the dark theme. The native element stays in  */
/* the DOM (hidden) so existing .value reads/writes still work.  */
/* ============================================================ */

function enhanceSelect(select) {
  const wrap = select.closest(".select");
  if (!wrap || wrap.querySelector(".select__trigger")) return;

  select.classList.add("select__native");
  select.setAttribute("tabindex", "-1");
  select.setAttribute("aria-hidden", "true");

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "select__trigger";
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  trigger.innerHTML = '<span class="select__value"></span>';
  wrap.insertBefore(trigger, select);

  const listbox = document.createElement("div");
  listbox.className = "select__listbox";
  listbox.setAttribute("role", "listbox");
  listbox.hidden = true;
  wrap.appendChild(listbox);

  let optionEls = [];
  let highlighted = -1;

  function rebuild() {
    listbox.innerHTML = "";
    optionEls = [];
    const groups = select.querySelectorAll(":scope > optgroup");
    if (groups.length) {
      for (const og of groups) {
        const label = document.createElement("div");
        label.className = "select__optgroup-label";
        label.textContent = og.label;
        listbox.appendChild(label);
        for (const opt of og.querySelectorAll(":scope > option")) {
          listbox.appendChild(buildOption(opt));
        }
      }
    } else {
      for (const opt of select.querySelectorAll(":scope > option")) {
        listbox.appendChild(buildOption(opt));
      }
    }
    syncTrigger();
  }

  function buildOption(opt) {
    const el = document.createElement("div");
    el.className = "select__option";
    el.dataset.value = opt.value;
    el.setAttribute("role", "option");
    el.textContent = opt.textContent;
    el.addEventListener("mousemove", () => {
      const idx = optionEls.indexOf(el);
      if (idx !== highlighted) {
        highlighted = idx;
        updateHighlight();
      }
    });
    el.addEventListener("click", () => choose(opt.value));
    optionEls.push(el);
    return el;
  }

  function syncTrigger() {
    const valueEl = trigger.querySelector(".select__value");
    const current = select.options[select.selectedIndex];
    valueEl.textContent = current ? current.textContent : "";
    for (const el of optionEls) {
      el.setAttribute(
        "aria-selected",
        el.dataset.value === select.value ? "true" : "false",
      );
    }
  }

  function choose(value) {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    close();
    trigger.focus();
  }

  function open() {
    if (!listbox.hidden) return;
    listbox.hidden = false;
    wrap.classList.add("select--open");
    trigger.setAttribute("aria-expanded", "true");
    highlighted = Math.max(
      0,
      optionEls.findIndex((el) => el.dataset.value === select.value),
    );
    updateHighlight();
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onDocKeyDown);
  }

  function close() {
    if (listbox.hidden) return;
    listbox.hidden = true;
    wrap.classList.remove("select--open");
    trigger.setAttribute("aria-expanded", "false");
    document.removeEventListener("mousedown", onDocMouseDown);
    document.removeEventListener("keydown", onDocKeyDown);
  }

  function updateHighlight() {
    optionEls.forEach((el, i) => {
      el.dataset.highlighted = i === highlighted ? "true" : "false";
    });
    if (highlighted >= 0 && optionEls[highlighted]) {
      optionEls[highlighted].scrollIntoView({ block: "nearest" });
    }
  }

  function onDocMouseDown(e) {
    if (!wrap.contains(e.target)) close();
  }

  function onDocKeyDown(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      trigger.focus();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      highlighted = Math.min(optionEls.length - 1, highlighted + 1);
      updateHighlight();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      highlighted = Math.max(0, highlighted - 1);
      updateHighlight();
    } else if (e.key === "Home") {
      e.preventDefault();
      highlighted = 0;
      updateHighlight();
    } else if (e.key === "End") {
      e.preventDefault();
      highlighted = optionEls.length - 1;
      updateHighlight();
    } else if (e.key === "Enter" || e.key === " ") {
      if (highlighted >= 0 && optionEls[highlighted]) {
        e.preventDefault();
        optionEls[highlighted].click();
      }
    } else if (e.key === "Tab") {
      close();
    }
  }

  trigger.addEventListener("click", () => (listbox.hidden ? open() : close()));
  trigger.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open();
    }
  });

  select.addEventListener("change", syncTrigger);
  new MutationObserver(rebuild).observe(select, {
    childList: true,
    subtree: true,
  });

  rebuild();
}

function updateModelHint() {
  const id = els.modelSelect.value;
  const model = state.models.find((m) => m.id === id);
  els.modelHint.textContent = model ? model.description : "";
}

function hydrateForm() {
  const p = state.preferences;
  els.inputFolder.value = p.input_folder ?? "";
  els.outputFolder.value = p.output_folder ?? "";
  els.skipExisting.checked = !!p.skip_existing;
  els.recursive.checked = !!p.recursive;
  els.force.checked = false;
  els.alphaMatting.checked = !!p.alpha_matting;
  els.amFg.value = p.alpha_matting_foreground_threshold ?? 240;
  els.amBg.value = p.alpha_matting_background_threshold ?? 10;
  els.amErode.value = p.alpha_matting_erode_size ?? 10;
  els.pngCompression.value = p.png_compression ?? 1;
  els.backgroundColor.value = p.background_color ?? "";
  if (p.background_color && /^#[0-9a-f]{6}/i.test(p.background_color)) {
    els.backgroundColorPicker.value = p.background_color.slice(0, 7);
  }
  els.workers.value = String(state.workersLocal);
}

function syncQualityFromModel(modelId) {
  const model = state.models.find((m) => m.id === modelId);
  if (!model) return;
  const preset = MODEL_QUALITY_TO_PRESET[model.quality] ?? "balanced";
  for (const btn of els.qualityButtons) {
    btn.setAttribute("aria-checked", btn.dataset.quality === preset ? "true" : "false");
  }
}

function updateWorkersDisplay() {
  const v = Number.parseInt(els.workers.value, 10);
  els.workersValue.textContent = v;
  const min = Number.parseInt(els.workers.min, 10) || 0;
  const max = Number.parseInt(els.workers.max, 10) || 100;
  const pct = ((v - min) / (max - min)) * 100;
  els.workers.style.setProperty("--slider-fill", `${pct}%`);
}

/* ============================================================ */
/* Preferences persistence (debounced)                           */
/* ============================================================ */

function collectPreferences() {
  return {
    input_folder: els.inputFolder.value.trim(),
    output_folder: els.outputFolder.value.trim(),
    model_name: els.modelSelect.value || state.defaultModel,
    skip_existing: els.skipExisting.checked,
    recursive: els.recursive.checked,
    png_compression: clampInt(els.pngCompression.value, 0, 9, 1),
    alpha_matting: els.alphaMatting.checked,
    alpha_matting_foreground_threshold: clampInt(els.amFg.value, 0, 255, 240),
    alpha_matting_background_threshold: clampInt(els.amBg.value, 0, 255, 10),
    alpha_matting_erode_size: clampInt(els.amErode.value, 0, 40, 10),
    background_color: els.backgroundColor.value.trim(),
  };
}

function schedulePreferencesSave() {
  if (state.saveTimer) clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => {
    state.saveTimer = null;
    persistPreferences().catch((err) => {
      console.warn("Persist failed", err);
      toast(`Could not save settings: ${err.message}`, "err");
    });
  }, 350);
}

async function persistPreferences() {
  const { preferences } = await api("/preferences", {
    method: "PUT",
    body: JSON.stringify(collectPreferences()),
  });
  state.preferences = preferences;
}

/* ============================================================ */
/* Folder probing                                                */
/* ============================================================ */

async function probeFolder(inputId) {
  const input = document.getElementById(inputId);
  const status = document.querySelector(`[data-status-for="${inputId}"]`);
  const path = input.value.trim();
  status.className = "path-input__status";
  if (!path) {
    status.textContent = "Type a path or use Choose folder.";
    return;
  }
  status.textContent = "Checking…";
  try {
    const result = await api("/folder/probe", {
      method: "POST",
      body: JSON.stringify({ path, recursive: els.recursive.checked }),
    });
    if (!result.exists) {
      status.className = "path-input__status path-input__status--err";
      status.textContent = result.error || "Folder does not exist.";
      return;
    }
    if (!result.is_directory) {
      status.className = "path-input__status path-input__status--err";
      status.textContent = "Path is not a directory.";
      return;
    }
    status.className = "path-input__status path-input__status--ok";
    if (inputId === "input-folder") {
      const sample = result.sample.length
        ? ` — ${result.sample.slice(0, 3).join(", ")}`
        : "";
      status.textContent = `Found ${result.image_count} image${result.image_count === 1 ? "" : "s"}${sample}`;
      els.statTotalPretty.textContent = formatNumber(result.image_count);
      els.statTotalHint.textContent = result.image_count > 0 ? "images in folder" : "no images yet";
      appendLog("info", "Input folder ready", {
        source: "folder",
        details: {
          images: result.image_count,
          recursive: els.recursive.checked,
        },
      });
    } else {
      status.textContent = `Directory ready (${result.image_count} existing).`;
      appendLog("info", "Output folder ready", {
        source: "folder",
        details: { existing: result.image_count },
      });
    }
  } catch (err) {
    status.className = "path-input__status path-input__status--err";
    status.textContent = err.message;
    appendLog("err", "Folder probe failed", {
      source: "folder",
      details: { path, error: err.message },
    });
  }
}

async function browseFolder(inputId) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const title =
    inputId === "input-folder" ? "Select input folder" : "Select output folder";
  try {
    const result = await api("/folder/pick", {
      method: "POST",
      body: JSON.stringify({
        initial_dir: input.value.trim(),
        title,
      }),
      // The user may sit on the native dialog for a while before choosing.
      timeoutMs: 0,
    });
    if (result.cancelled || !result.path) return;
    input.value = result.path;
    schedulePreferencesSave();
    await probeFolder(inputId);
  } catch (err) {
    appendLog("err", "Folder picker failed", {
      source: "folder",
      details: { error: err.message },
    });
    toast(`Could not open folder picker: ${err.message}`, "err");
  }
}

/* ============================================================ */
/* Dropzone                                                      */
/* ============================================================ */

function wireDropzone() {
  if (!els.dropzone) return;
  els.dropzone.addEventListener("click", () => browseFolder("input-folder"));
  els.dropzone.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      void browseFolder("input-folder");
    }
  });

  els.folderPicker?.addEventListener("change", () => {
    const files = Array.from(els.folderPicker.files ?? []);
    if (!files.length) return;
    handleSelectedFiles(files);
    els.folderPicker.value = "";
  });

  ["dragenter", "dragover"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      els.dropzone.classList.add("dropzone--active");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      els.dropzone.classList.remove("dropzone--active");
    })
  );

  els.dropzone.addEventListener("drop", async (e) => {
    const items = e.dataTransfer?.items;
    if (!items?.length) return;
    const folderHint = await firstFolderName(items);
    if (folderHint) {
      pickHint(folderHint);
    } else if (e.dataTransfer.files?.length) {
      handleSelectedFiles(Array.from(e.dataTransfer.files));
    }
  });
}

function handleSelectedFiles(files) {
  const first = files[0];
  const rel = first.webkitRelativePath || "";
  const folderHint = rel.includes("/") ? rel.split("/")[0] : null;
  if (folderHint) {
    pickHint(folderHint, files.length);
  } else {
    toast(`${files.length} file(s) staged — paste the absolute folder path below.`, "ok");
    els.inputFolder.focus();
  }
}

function pickHint(folderName, count = 0) {
  if (!els.inputFolder.value.trim()) {
    els.inputFolder.value = folderName;
  }
  const suffix = count ? ` (${count} files)` : "";
  toast(
    `Detected "${folderName}"${suffix}. Browsers can't read absolute paths — type the full path then Check.`,
    "ok"
  );
  els.inputFolder.focus();
  els.inputFolder.select();
}

async function firstFolderName(items) {
  for (const item of items) {
    const entry = item.webkitGetAsEntry?.();
    if (entry?.isDirectory) return entry.name;
  }
  return null;
}

/* ============================================================ */
/* Job lifecycle                                                 */
/* ============================================================ */

async function startJob() {
  try {
    await persistPreferences();
  } catch (err) {
    toast(`Could not save settings: ${err.message}`, "err");
    return;
  }
  els.startBtn.disabled = true;
  state.records.clear();
  state.lastJobError = "";
  renderQueue();
  renderThumbs();
  const prefs = state.preferences ?? {};
  appendLog("info", "Batch starting", {
    source: "job",
    details: {
      model: prefs.model_name ?? state.defaultModel,
      workers: state.workersLocal,
      skip: !!prefs.skip_existing,
      recursive: !!prefs.recursive,
      force: els.force.checked,
    },
  });
  showLoader(prefs.model_name);
  try {
    const status = await api("/job", {
      method: "POST",
      body: JSON.stringify({ force: els.force.checked }),
    });
    applyStatus(status);
    showScreen("live");
  } catch (err) {
    els.startBtn.disabled = false;
    hideLoader();
    toast(err.message, "err");
    appendLog("err", "Batch start failed", {
      source: "job",
      details: { error: err.message },
    });
  }
}

async function cancelJob() {
  try {
    const status = await api("/job", { method: "DELETE" });
    applyStatus(status);
    appendLog("warn", "Cancellation requested", { source: "job" });
  } catch (err) {
    toast(err.message, "err");
    appendLog("err", "Cancel request failed", {
      source: "job",
      details: { error: err.message },
    });
  }
}

/* ============================================================ */
/* WebSocket                                                     */
/* ============================================================ */

function connectWebSocket() {
  if (state.reconnectTimer) {
    clearTimeout(state.reconnectTimer);
    state.reconnectTimer = null;
  }
  // Tear down any in-flight socket so its handlers can't race the new one.
  if (state.socket && state.socket.readyState <= WebSocket.OPEN) {
    try {
      state.socket.close();
    } catch (_) {
      /* ignore */
    }
  }

  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${window.location.host}/ws/progress`;
  const sock = new WebSocket(url);
  state.socket = sock;
  setConnection("idle", "Connecting…", "live channel");

  sock.addEventListener("open", () => {
    if (state.socket !== sock) return;
    state.reconnectDelay = 1500;
    setConnection("ok", "Live", "live channel");
    if (state.wsState === "closed") {
      appendLog("ok", "Live channel reconnected", { source: "ws" });
    }
    state.wsState = "open";
  });
  sock.addEventListener("close", () => {
    if (state.socket !== sock) return;
    setConnection("err", "Offline", "reconnecting…");
    if (state.wsState === "open") {
      appendLog("warn", "Live channel disconnected", { source: "ws" });
    }
    state.wsState = "closed";
    scheduleReconnect();
  });
  sock.addEventListener("error", () => {
    if (state.socket !== sock) return;
    setConnection("err", "Offline", "disconnected");
  });
  sock.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(event.data);
      handleEvent(payload);
    } catch (err) {
      console.warn("Bad WS payload", err);
    }
  });
}

function scheduleReconnect() {
  if (state.reconnectTimer) return;
  const delay = state.reconnectDelay;
  state.reconnectDelay = Math.min(delay * 2, 15000);
  state.reconnectTimer = setTimeout(() => {
    state.reconnectTimer = null;
    connectWebSocket();
  }, delay);
}

function setConnection(kind, label, sub) {
  const pill = els.statusPill;
  pill.classList.remove("status-pill--ok", "status-pill--err", "status-pill--running");
  if (kind === "ok") pill.classList.add("status-pill--ok");
  if (kind === "err") pill.classList.add("status-pill--err");
  if (kind === "running") pill.classList.add("status-pill--running");
  els.statusPillTitle.textContent = label;
  els.statusPillSub.textContent = sub;

  const cb = els.connBadge;
  cb.classList.remove("conn-badge--ok", "conn-badge--err");
  if (kind === "ok") cb.classList.add("conn-badge--ok");
  if (kind === "err") cb.classList.add("conn-badge--err");
  const cbLabel = cb.querySelector(".conn-badge__label");
  if (cbLabel) cbLabel.textContent = label.toLowerCase();
}

function handleEvent(payload) {
  const status = payload?.status;
  if (!status) return;

  if (payload.type === "item" && status.current_file) {
    recordFile(status);
  }

  applyStatus(status);

  if (payload.type === "done") {
    const s = status.state ?? "completed";
    const tail = payload.message ? ` — ${payload.message}` : "";
    const summary = {
      processed: status.processed ?? 0,
      skipped: status.skipped ?? 0,
      failed: status.failed ?? 0,
      elapsed: formatDuration(status.duration_seconds ?? 0),
    };
    if (s === "completed") {
      appendLog("ok", "Batch complete", { source: "job", details: summary });
      toast(`Batch complete: ${status.processed} processed.`, "ok");
    } else if (s === "cancelled") {
      appendLog("warn", "Batch cancelled", {
        source: "job",
        details: payload.message ? { ...summary, reason: payload.message } : summary,
      });
    } else if (s === "failed") {
      appendLog("err", "Batch failed", {
        source: "job",
        details: payload.message ? { ...summary, error: payload.message } : summary,
      });
      toast(`Batch failed${tail}`, "err");
    }
    void refreshOutputGrid();
  }
}

/* ============================================================ */
/* Status rendering                                              */
/* ============================================================ */

function applyStatus(status) {
  if (state.prevState !== "running" && status.state === "running") {
    state.prevCounts = { processed: 0, skipped: 0, failed: 0 };
    state.lastJobError = "";
  }
  state.lastStatus = status;

  const total = status.total ?? 0;
  const processed = status.processed ?? 0;
  const skipped = status.skipped ?? 0;
  const failed = status.failed ?? 0;
  const done = processed + skipped + failed;
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;

  els.heroProcessed.textContent = formatNumber(processed);
  els.heroTotal.textContent = formatNumber(total);
  els.statProcessed.textContent = processed;
  els.statSkipped.textContent = skipped;
  els.statFailed.textContent = failed;
  els.statPercent.textContent = `${pct.toFixed(0)}%`;
  els.progressFill.style.width = `${pct}%`;

  setStateBadge(status.state);
  els.heroSub.textContent = composeHeroSub(status);

  if (status.average_seconds_per_image && status.average_seconds_per_image > 0) {
    const ips = 1 / status.average_seconds_per_image;
    els.statThroughput.textContent = ips.toFixed(2);
    if (status.state === "running") {
      els.statEta.textContent = formatDuration(
        Math.max(0, total - done) * status.average_seconds_per_image
      );
      els.statEtaHint.textContent = "until done";
    } else if (status.state === "completed") {
      els.statEta.textContent = "0s";
      els.statEtaHint.textContent = "complete";
    } else {
      els.statEta.textContent = "—";
      els.statEtaHint.textContent = status.state;
    }
  } else {
    els.statThroughput.textContent = "—";
    els.statEta.textContent = "—";
    els.statEtaHint.textContent = status.state === "idle" ? "no job" : status.state;
  }

  if (total > 0) {
    els.statTotalPretty.textContent = formatNumber(total);
    els.statTotalHint.textContent = "this batch";
  }
  els.statTimeSaved.textContent = formatDuration(status.duration_seconds ?? 0);
  els.statFailures.textContent = failed;
  els.statFailuresHint.textContent = failed > 0 ? "see logs for details" : "All clean";

  if (status.state === "running" && total > 0) {
    setConnection("running", `Running ${processed}/${total}`, "batch in progress");
  } else if (status.state === "completed") {
    setConnection("ok", "Live", "batch complete");
  }

  const isRunning = status.state === "running" || status.state === "cancelling";
  els.startBtn.disabled = isRunning;
  els.cancelBtn.disabled = !isRunning || status.state === "cancelling";
  els.liveCancelBtn.disabled = !isRunning || status.state === "cancelling";

  if (status.last_error && status.last_error !== state.lastJobError) {
    appendLog("err", status.last_error, { source: "job" });
    state.lastJobError = status.last_error;
  }

  // Drop the loading modal as soon as we have evidence the model is loaded:
  // either a file is being worked on, the first result has landed, or the
  // job left the running state altogether (failed warmup, empty folder…).
  if (state.loaderActive) {
    const movedPastWarmup =
      status.state !== "running" || !!status.current_file || done > 0;
    if (movedPastWarmup) {
      hideLoader();
    }
  }

  state.prevState = status.state;
  state.prevCounts = { processed, skipped, failed };
}

function setStateBadge(s) {
  const badge = els.stateBadge;
  if (!badge) return;
  badge.classList.remove(
    "badge--idle",
    "badge--running",
    "badge--success",
    "badge--failed",
    "badge--warning",
    "badge--queued"
  );
  const map = {
    idle: ["badge--idle", "idle"],
    running: ["badge--running", "running"],
    cancelling: ["badge--warning", "cancelling"],
    cancelled: ["badge--warning", "cancelled"],
    completed: ["badge--success", "completed"],
    failed: ["badge--failed", "failed"],
  };
  const [cls, label] = map[s] ?? ["badge--idle", s ?? "idle"];
  badge.classList.add(cls);
  const text = badge.querySelector(".badge__text");
  if (text) text.textContent = label;
}

function composeHeroSub(status) {
  switch (status.state) {
    case "idle":
      return "Choose a folder and start a batch to begin.";
    case "running":
      return status.current_file ? `Now processing ${status.current_file}…` : "Warming up the model…";
    case "cancelling":
      return "Stopping at the next image boundary…";
    case "cancelled":
      return "Job cancelled. Press Start to resume from where you left off.";
    case "completed":
      return `Done. ${formatDuration(status.duration_seconds ?? 0)} elapsed.`;
    case "failed":
      return status.last_error ? `Failed: ${status.last_error}` : "Job failed.";
    default:
      return "";
  }
}

/* ============================================================ */
/* Records / queue / thumbs                                      */
/* ============================================================ */

function recordFile(status) {
  const name = status.current_file;
  if (!name) return;

  const inc = {
    processed: (status.processed ?? 0) - state.prevCounts.processed,
    skipped: (status.skipped ?? 0) - state.prevCounts.skipped,
    failed: (status.failed ?? 0) - state.prevCounts.failed,
  };
  let fileStatus = "running";
  if (inc.failed > 0) fileStatus = "failed";
  else if (inc.skipped > 0) fileStatus = "skipped";
  else if (inc.processed > 0) fileStatus = "done";

  if (fileStatus === "running") return;

  state.records.set(name, {
    name,
    status: fileStatus,
    model: state.preferences?.model_name ?? "—",
    durationSec: status.average_seconds_per_image ?? undefined,
    outputRelative: status.current_output_relative ?? null,
  });

  if (fileStatus === "failed") {
    appendLog("err", `${name} failed`, { source: "job" });
  }

  renderQueue();
  renderThumbs();
}

function renderQueue() {
  const records = Array.from(state.records.values()).reverse();

  if (!records.length) {
    els.queueBody.innerHTML = "";
    els.queueEmpty.hidden = false;
    els.queueBody.append(els.queueEmpty);
    els.queueCount.textContent = "No files yet.";
    return;
  }

  els.queueCount.textContent = `${records.length} tracked.`;
  els.queueEmpty.hidden = true;
  const rows = records.slice(0, 30).map(rowMarkup).join("");
  els.queueBody.innerHTML = rows;
}

function rowMarkup(r) {
  const cls = badgeClassFor(r.status);
  const dur = r.durationSec ? `${r.durationSec.toFixed(1)}s` : "—";
  return (
    `<div class="filerow">` +
    `  <span class="filerow__icon"><span>` +
    `    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">` +
    `      <rect x="3" y="3" width="18" height="18" rx="2"/>` +
    `      <circle cx="9" cy="9" r="2"/>` +
    `      <path d="m21 15-3.5-3.5a2 2 0 0 0-2.8 0L4 22"/>` +
    `    </svg>` +
    `  </span></span>` +
    `  <div class="filerow__info">` +
    `    <div class="filerow__name" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</div>` +
    `    <div class="filerow__meta">${escapeHtml(r.model)}</div>` +
    `  </div>` +
    `  <span class="badge ${cls}"><span class="badge__dot"></span><span class="badge__text">${r.status}</span></span>` +
    `  <span class="filerow__duration">${dur}</span>` +
    `</div>`
  );
}

function badgeClassFor(status) {
  switch (status) {
    case "running":
      return "badge--running";
    case "done":
      return "badge--success";
    case "skipped":
      return "badge--idle";
    case "failed":
      return "badge--failed";
    case "queued":
    default:
      return "badge--queued";
  }
}

function renderThumbs() {
  const filter = state.resultFilter;
  const all = Array.from(state.records.values()).reverse();
  const items = all.filter((r) => {
    if (filter === "all") return true;
    if (filter === "done") return r.status === "done";
    if (filter === "failed") return r.status === "failed";
    return true;
  });

  if (!items.length) {
    els.thumbs.innerHTML = "";
    els.thumbsEmpty.hidden = false;
    els.thumbs.append(els.thumbsEmpty);
    return;
  }
  els.thumbsEmpty.hidden = true;
  els.thumbs.innerHTML = "";
  for (const r of items.slice(0, 24)) {
    els.thumbs.append(buildThumb(r));
  }
}

function buildThumb(r) {
  const card = document.createElement("div");
  card.className = "thumb";
  if (r.status === "failed") card.classList.add("thumb--failed");
  if (r.status === "skipped" || r.status === "queued") card.classList.add("thumb--queued");

  const imageCell = document.createElement("div");
  imageCell.className = "thumb__image";

  let outputPath = null;
  if (r.status === "failed") {
    imageCell.innerHTML = `<span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17v.5"/></svg></span>`;
  } else if (r.status === "done") {
    // Prefer the relative path reported by the server (handles recursive
    // input where the file lives in a subfolder); fall back to swapping
    // the extension on the bare name for older payloads.
    outputPath = r.outputRelative || `${r.name.replace(/\.[^.]+$/, "")}.png`;
    const img = document.createElement("img");
    img.alt = r.name;
    img.loading = "lazy";
    img.decoding = "async";
    img.src = `/api/output/file?path=${encodeURIComponent(outputPath)}`;
    imageCell.append(img);
  } else {
    imageCell.innerHTML = `<span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></span>`;
  }

  card.append(imageCell);
  const meta = document.createElement("div");
  meta.className = "thumb__meta";
  meta.innerHTML = `<div class="thumb__name" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</div><div class="thumb__sub">${escapeHtml(r.status)}${r.durationSec ? " · " + r.durationSec.toFixed(1) + "s" : ""}</div>`;
  card.append(meta);

  if (outputPath) {
    makeThumbClickable(card, {
      src: `/api/output/file?path=${encodeURIComponent(outputPath)}`,
      name: r.name,
      sub: r.durationSec ? `${r.durationSec.toFixed(1)}s · processed` : "processed",
    });
  }
  return card;
}

function makeThumbClickable(card, item) {
  card.classList.add("thumb--clickable");
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-label", `Open ${item.name} in preview`);
  card.dataset.lightbox = "1";
  card.addEventListener("click", () => openLightboxForCard(card));
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openLightboxForCard(card);
    }
  });
  // Stash the item so the host grid can rebuild its index when opening.
  card._lightboxItem = item;
}

function openLightboxForCard(card) {
  const grid = card.parentElement;
  if (!grid) return;
  const siblings = Array.from(grid.querySelectorAll(".thumb--clickable"));
  const items = siblings.map((el) => el._lightboxItem).filter(Boolean);
  const index = siblings.indexOf(card);
  if (index < 0 || !items.length) return;
  openLightbox(items, index, card);
}

/* ============================================================ */
/* Output folder grid                                            */
/* ============================================================ */

async function refreshOutputGrid() {
  if (!els.outputGrid) return;
  try {
    const data = await api("/output?limit=48");
    const folder = data?.folder || "";
    const files = data?.files || [];
    if (els.outputFolderLabel) {
      els.outputFolderLabel.textContent = folder
        ? `Browsing ${folder} — newest first.`
        : "Configure an output folder to browse the produced files.";
    }
    if (!files.length) {
      els.outputGrid.innerHTML = "";
      els.outputEmpty.hidden = false;
      els.outputEmpty.textContent = folder
        ? "No PNGs in the output folder yet."
        : "Configure an output folder to browse the produced files.";
      els.outputGrid.append(els.outputEmpty);
      state.outputItems = [];
      return;
    }
    els.outputEmpty.hidden = true;
    els.outputGrid.innerHTML = "";
    state.outputItems = files.map((file) => ({
      src: `/api/output/file?path=${encodeURIComponent(file.relative_path)}`,
      name: file.name,
      sub: `${formatBytes(file.size_bytes)} · ${formatRelative(file.modified_at)}`,
    }));
    for (const item of state.outputItems) {
      els.outputGrid.append(buildOutputCard(item));
    }
  } catch (err) {
    toast(`Could not list output: ${err.message}`, "err");
  }
}

function buildOutputCard(item) {
  const card = document.createElement("div");
  card.className = "thumb";

  const imageCell = document.createElement("div");
  imageCell.className = "thumb__image";
  const img = document.createElement("img");
  img.alt = item.name;
  img.loading = "lazy";
  img.decoding = "async";
  img.src = item.src;
  imageCell.append(img);

  const meta = document.createElement("div");
  meta.className = "thumb__meta";
  const nameEl = document.createElement("div");
  nameEl.className = "thumb__name";
  nameEl.title = item.name;
  nameEl.textContent = item.name;
  const subEl = document.createElement("div");
  subEl.className = "thumb__sub";
  subEl.textContent = item.sub;
  meta.append(nameEl, subEl);

  card.append(imageCell, meta);
  makeThumbClickable(card, item);
  return card;
}

/* ============================================================ */
/* Logs / toast                                                  */
/* ============================================================ */

const MAX_LOG_ENTRIES = 250;
const LOG_LEVELS = ["info", "ok", "warn", "err"];
const LOG_LEVEL_LABEL = { info: "INFO", ok: "OK", warn: "WARN", err: "ERR" };
const LOG_FILTER_NOUN = {
  info: "info", ok: "ok", warn: "warning", err: "error",
};

/**
 * Append a structured event to the activity log.
 *
 * @param {"info"|"ok"|"warn"|"err"} level
 * @param {string} message
 * @param {{ source?: string, details?: Record<string, unknown> }} [opts]
 */
function appendLog(level, message, opts = {}) {
  if (!els.logs) return;
  const lvl = LOG_LEVELS.includes(level) ? level : "info";
  const entry = {
    id: state.logs.nextId++,
    level: lvl,
    source: opts.source ?? "system",
    message: String(message ?? ""),
    details: opts.details ?? null,
    time: new Date(),
  };
  state.logs.entries.push(entry);
  state.logs.counts[lvl] += 1;

  while (state.logs.entries.length > MAX_LOG_ENTRIES) {
    const dropped = state.logs.entries.shift();
    if (dropped) {
      state.logs.counts[dropped.level] = Math.max(
        0, state.logs.counts[dropped.level] - 1
      );
    }
  }
  renderLogs();
}

function renderLogs() {
  if (!els.logs) return;
  const filter = state.logs.filter;
  const matches = filter === "all"
    ? state.logs.entries
    : state.logs.entries.filter((e) => e.level === filter);

  // Always keep the empty-state node as the first child so we can toggle it
  // cheaply without re-creating it on every render.
  els.logs.replaceChildren(els.logsEmpty);
  if (matches.length) {
    els.logsEmpty.hidden = true;
    const html = [];
    for (let i = matches.length - 1; i >= 0; i--) {
      html.push(renderLogEntry(matches[i]));
    }
    els.logs.insertAdjacentHTML("beforeend", html.join(""));
  } else {
    els.logsEmpty.hidden = false;
    els.logsEmpty.textContent = state.logs.entries.length
      ? `No ${LOG_FILTER_NOUN[filter] ?? filter} entries in this session.`
      : "No events yet — start a batch to see live activity.";
  }
  syncLogCounts();
}

function renderLogEntry(e) {
  const timeStr = e.time.toLocaleTimeString([], { hour12: false });
  const label = LOG_LEVEL_LABEL[e.level] ?? e.level.toUpperCase();
  let details = "";
  if (e.details && typeof e.details === "object") {
    const chips = [];
    for (const [k, v] of Object.entries(e.details)) {
      if (v === undefined || v === null || v === "") continue;
      chips.push(
        `<span class="log-entry__detail"><b>${escapeHtml(k)}</b>${escapeHtml(formatDetailValue(v))}</span>`
      );
    }
    if (chips.length) {
      details = `<span class="log-entry__details">${chips.join("")}</span>`;
    }
  }
  return (
    `<div class="log-entry" data-level="${e.level}">` +
    `<span class="log-entry__time">${escapeHtml(timeStr)}</span>` +
    `<span class="log-entry__level log-entry__level--${e.level}">${escapeHtml(label)}</span>` +
    `<span class="log-entry__source">${escapeHtml(e.source)}</span>` +
    `<span class="log-entry__msg">${escapeHtml(e.message)}${details}</span>` +
    `</div>`
  );
}

function formatDetailValue(v) {
  if (typeof v === "boolean") return v ? "on" : "off";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "—";
  return String(v);
}

function syncLogCounts() {
  const total = state.logs.entries.length;
  for (const btn of els.logFilterButtons) {
    const f = btn.dataset.logFilter;
    const slot = btn.querySelector(".log-filter__count");
    if (!slot) continue;
    slot.textContent = formatNumber(f === "all" ? total : state.logs.counts[f] ?? 0);
  }
}

function setLogFilter(filter) {
  if (filter !== "all" && !LOG_LEVELS.includes(filter)) return;
  state.logs.filter = filter;
  for (const btn of els.logFilterButtons) {
    btn.setAttribute(
      "aria-checked",
      btn.dataset.logFilter === filter ? "true" : "false"
    );
  }
  renderLogs();
}

function clearLogs() {
  state.logs.entries = [];
  state.logs.counts = { info: 0, ok: 0, warn: 0, err: 0 };
  renderLogs();
}

async function copyLogs() {
  const filter = state.logs.filter;
  const rows = filter === "all"
    ? state.logs.entries
    : state.logs.entries.filter((e) => e.level === filter);
  if (!rows.length) {
    toast("No log entries to copy.", "err");
    return;
  }
  const lines = rows.map((e) => {
    const t = e.time.toLocaleTimeString([], { hour12: false });
    const lvl = (LOG_LEVEL_LABEL[e.level] ?? e.level).padEnd(4);
    const src = (e.source ?? "").padEnd(8);
    const details = e.details
      ? " " + Object.entries(e.details)
          .filter(([, v]) => v !== undefined && v !== null && v !== "")
          .map(([k, v]) => `${k}=${formatDetailValue(v)}`)
          .join(" ")
      : "";
    return `${t}  ${lvl}  ${src}  ${e.message}${details}`;
  });
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    toast(`Copied ${lines.length} log ${lines.length === 1 ? "entry" : "entries"}.`, "ok");
  } catch (err) {
    toast(`Copy failed: ${err.message}`, "err");
  }
}

/* ============================================================ */
/* Loader modal                                                  */
/* ============================================================ */

function modelLabelFor(id) {
  const model = state.models.find((m) => m.id === id);
  return model?.label ?? id ?? "model";
}

function showLoader(modelId) {
  if (!els.loaderModal) return;
  els.loaderModelName.textContent = modelLabelFor(modelId);
  els.loaderElapsed.textContent = "Preparing the inference graph";
  els.loaderModal.hidden = false;
  state.loaderActive = true;
  state.loaderStartedAt = performance.now();
  if (state.loaderTimer) clearInterval(state.loaderTimer);
  // Update the elapsed-time hint once per second. It reassures the user
  // when the first-run weight download stretches well past the spinner
  // cadence (rembg silently downloads to ~/.u2net on the first session).
  state.loaderTimer = setInterval(() => {
    if (!state.loaderActive) return;
    const sec = Math.floor((performance.now() - state.loaderStartedAt) / 1000);
    if (sec < 4) {
      els.loaderElapsed.textContent = "Preparing the inference graph";
    } else if (sec < 12) {
      els.loaderElapsed.textContent = `Building ONNX session · ${sec}s`;
    } else {
      els.loaderElapsed.textContent =
        `Still loading · ${sec}s · first run may download weights`;
    }
  }, 500);
}

function hideLoader() {
  if (!els.loaderModal || !state.loaderActive) return;
  state.loaderActive = false;
  if (state.loaderTimer) {
    clearInterval(state.loaderTimer);
    state.loaderTimer = null;
  }
  els.loaderModal.hidden = true;
}

/* ============================================================ */
/* Lightbox                                                      */
/* ============================================================ */

function openLightbox(items, index, originEl) {
  if (!els.lightbox || !items.length) return;
  state.lightbox.items = items;
  state.lightbox.index = Math.max(0, Math.min(items.length - 1, index));
  state.lightbox.lastFocus = originEl || document.activeElement;
  els.lightbox.hidden = false;
  document.body.style.overflow = "hidden";
  renderLightbox();
  els.lightbox.addEventListener("click", onLightboxClick);
  document.addEventListener("keydown", onLightboxKey);
  // Defer focus so the dialog is paintable before we steal focus.
  requestAnimationFrame(() => els.lightboxNext?.focus({ preventScroll: true }));
}

function closeLightbox() {
  if (!els.lightbox || els.lightbox.hidden) return;
  els.lightbox.hidden = true;
  document.body.style.overflow = "";
  els.lightbox.removeEventListener("click", onLightboxClick);
  document.removeEventListener("keydown", onLightboxKey);
  els.lightboxImg.removeAttribute("src");
  const prior = state.lightbox.lastFocus;
  state.lightbox = { items: [], index: -1, lastFocus: null };
  if (prior && typeof prior.focus === "function") {
    try { prior.focus({ preventScroll: true }); } catch (_) { /* noop */ }
  }
}

function stepLightbox(delta) {
  const { items, index } = state.lightbox;
  if (!items.length) return;
  const next = index + delta;
  if (next < 0 || next >= items.length) return;
  state.lightbox.index = next;
  renderLightbox();
}

function renderLightbox() {
  const { items, index } = state.lightbox;
  const item = items[index];
  if (!item) return;
  els.lightboxImg.src = item.src;
  els.lightboxImg.alt = item.name;
  els.lightboxTitle.textContent = item.name;
  els.lightboxSub.textContent = item.sub || "";
  els.lightboxCounter.textContent =
    items.length > 1 ? `${index + 1} / ${items.length}` : "";
  if (els.lightboxDownload) {
    els.lightboxDownload.href = item.src;
    els.lightboxDownload.setAttribute("download", item.name);
  }
  els.lightboxPrev.disabled = index <= 0;
  els.lightboxNext.disabled = index >= items.length - 1;
}

function onLightboxClick(event) {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest("[data-lightbox-close]")) {
    closeLightbox();
  }
}

function onLightboxKey(event) {
  switch (event.key) {
    case "Escape":
      event.preventDefault();
      closeLightbox();
      break;
    case "ArrowLeft":
      event.preventDefault();
      stepLightbox(-1);
      break;
    case "ArrowRight":
      event.preventDefault();
      stepLightbox(1);
      break;
    case "Home":
      event.preventDefault();
      state.lightbox.index = 0;
      renderLightbox();
      break;
    case "End":
      event.preventDefault();
      state.lightbox.index = state.lightbox.items.length - 1;
      renderLightbox();
      break;
  }
}

function toast(message, kind = "ok") {
  if (!els.toast) return;
  els.toast.hidden = false;
  els.toast.textContent = message;
  if (kind === "ok") {
    els.toast.style.borderColor = "rgba(34, 197, 94, 0.5)";
    els.toast.style.color = "var(--success)";
  } else {
    els.toast.style.borderColor = "rgba(239, 68, 68, 0.5)";
    els.toast.style.color = "var(--danger)";
  }
  if (state.toastTimer) clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => {
    els.toast.hidden = true;
  }, 4000);
}

/* ============================================================ */
/* Navigation                                                    */
/* ============================================================ */

function showScreen(name) {
  if (!SCREENS[name]) return;
  for (const item of els.navItems) {
    item.classList.toggle("nav-item--active", item.dataset.screen === name);
  }
  for (const vp of els.viewports) {
    vp.hidden = vp.dataset.screen !== name;
  }
  const meta = SCREENS[name];
  els.screenTitle.textContent = meta.title;
  els.screenSubtitle.textContent = meta.subtitle;
  document.body.dataset.screen = name;
  if (name === "output") void refreshOutputGrid();
}

/* ============================================================ */
/* CSV export                                                    */
/* ============================================================ */

function exportCsv() {
  const rows = Array.from(state.records.values());
  if (!rows.length) {
    toast("No records to export yet.", "err");
    return;
  }
  const header = ["filename", "status", "model", "duration_sec"];
  const lines = [header.join(",")];
  for (const r of rows) {
    lines.push(
      [
        `"${r.name.replaceAll('"', '""')}"`,
        r.status,
        r.model ?? "",
        r.durationSec ?? "",
      ].join(",")
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `delete-background-${Date.now()}.csv`;
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* ============================================================ */
/* Event wiring                                                  */
/* ============================================================ */

function wireEvents() {
  for (const item of els.navItems) {
    item.addEventListener("click", () => showScreen(item.dataset.screen));
  }

  for (const button of $$("[data-probe]")) {
    button.addEventListener("click", () => probeFolder(button.dataset.probe));
  }

  for (const button of $$("[data-browse]")) {
    button.addEventListener("click", () => browseFolder(button.dataset.browse));
  }

  const debounced = [
    els.inputFolder,
    els.outputFolder,
    els.amFg,
    els.amBg,
    els.amErode,
    els.pngCompression,
    els.backgroundColor,
  ];
  for (const input of debounced) {
    input.addEventListener("input", schedulePreferencesSave);
  }
  for (const cb of [els.skipExisting, els.recursive, els.alphaMatting]) {
    cb.addEventListener("change", schedulePreferencesSave);
  }

  els.modelSelect.addEventListener("change", () => {
    syncQualityFromModel(els.modelSelect.value);
    updateModelHint();
    schedulePreferencesSave();
  });

  for (const btn of els.qualityButtons) {
    btn.addEventListener("click", () => {
      const q = btn.dataset.quality;
      const target = QUALITY_TO_MODEL[q];
      if (target && state.models.some((m) => m.id === target)) {
        els.modelSelect.value = target;
        // Fire change so the custom combobox trigger label updates too.
        els.modelSelect.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  }

  els.workers.addEventListener("input", () => {
    updateWorkersDisplay();
    state.workersLocal = Number.parseInt(els.workers.value, 10);
    localStorage.setItem("dbg.workers", String(state.workersLocal));
  });

  els.backgroundColorPicker.addEventListener("input", () => {
    els.backgroundColor.value = els.backgroundColorPicker.value;
    schedulePreferencesSave();
  });

  els.startBtn.addEventListener("click", startJob);
  els.cancelBtn.addEventListener("click", cancelJob);
  els.liveCancelBtn.addEventListener("click", cancelJob);
  els.exportCsvBtn.addEventListener("click", exportCsv);
  els.chooseFolderBtn?.addEventListener("click", () => browseFolder("input-folder"));

  for (const btn of els.resultFilters) {
    btn.addEventListener("click", () => {
      state.resultFilter = btn.dataset.filter;
      for (const b of els.resultFilters) {
        b.setAttribute("aria-checked", b === btn ? "true" : "false");
      }
      renderThumbs();
    });
  }

  els.outputRefreshBtn?.addEventListener("click", () => void refreshOutputGrid());

  els.lightboxPrev?.addEventListener("click", () => stepLightbox(-1));
  els.lightboxNext?.addEventListener("click", () => stepLightbox(1));
  els.logsClearBtn?.addEventListener("click", clearLogs);
  els.logsCopyBtn?.addEventListener("click", () => void copyLogs());
  for (const btn of els.logFilterButtons) {
    btn.addEventListener("click", () => setLogFilter(btn.dataset.logFilter));
  }

  wireDropzone();

  window.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $("#search")?.focus();
    }
  });

  window.addEventListener("beforeunload", () => state.socket?.close());
}

/* ============================================================ */
/* Boot                                                          */
/* ============================================================ */

wireEvents();
enhanceSelect(els.modelSelect);
showScreen("dashboard");
bootstrap();
