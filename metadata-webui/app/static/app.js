const state = {
  index: [],
  filtered: [],
  selectedPaths: new Set(),
  activePath: null,
};

const editableFields = [
  "album",
  "albumartist",
  "artist",
  "title",
  "tracknumber",
  "discnumber",
  "compilation",
  "date",
];

const tracksBody = document.getElementById("tracks-body");
const searchInput = document.getElementById("search-input");
const selectVisibleBtn = document.getElementById("select-visible-btn");
const rescanBtn = document.getElementById("rescan-btn");
const batchBar = document.getElementById("batch-bar");
const batchCount = document.getElementById("batch-count");
const batchForm = document.getElementById("batch-form");
const batchLoading = document.getElementById("batch-loading");
const applySelectedBtn = document.getElementById("apply-selected-btn");
const editorPanel = document.getElementById("editor-panel");
const editorPath = document.getElementById("editor-path");
const trackForm = document.getElementById("track-form");
const closeEditorBtn = document.getElementById("close-editor-btn");
const message = document.getElementById("message");

function errorToString(err) {
  if (!err) {
    return "Unknown error";
  }
  if (typeof err === "string") {
    return err;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return String(err);
}

function sendFrontendLog(payload) {
  fetch("api/frontend-log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {
    // Never throw from logging.
  });
}

function showMessage(text, isError = false) {
  message.textContent = text;
  message.classList.add("visible");
  message.classList.toggle("error", isError);
  window.setTimeout(() => {
    message.classList.remove("visible");
    message.classList.remove("error");
  }, 2200);
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch (err) {
      // Ignore body parse errors and keep generic detail.
    }
    sendFrontendLog({
      level: "error",
      source: "api",
      message: "API request failed",
      context: { path, method: options.method || "GET", detail, status: response.status },
    });
    throw new Error(detail);
  }
  return response.json();
}

function renderTable() {
  tracksBody.innerHTML = "";
  for (const track of state.filtered) {
    const row = document.createElement("tr");
    row.dataset.path = track.path;

    row.innerHTML = `
      <td><input type="checkbox" data-path="${track.path}" ${state.selectedPaths.has(track.path) ? "checked" : ""}></td>
      <td>${track.title || ""}</td>
      <td>${track.artist || ""}</td>
      <td>${track.album || ""}</td>
      <td>${track.albumartist || ""}</td>
      <td>${track.tracknumber || ""}</td>
      <td>${track.discnumber || ""}</td>
    `;
    tracksBody.appendChild(row);
  }
}

function applySearch() {
  const query = searchInput.value.trim().toLowerCase();
  if (!query) {
    state.filtered = [...state.index];
    renderTable();
    return;
  }

  state.filtered = state.index.filter((track) => {
    const text = [track.title, track.artist, track.album, track.albumartist]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return text.includes(query);
  });
  renderTable();
}

function updateBatchBar() {
  const selected = state.selectedPaths.size;
  batchCount.textContent = `${selected} selected`;
  batchBar.classList.toggle("hidden", selected === 0);
}

function selectAllVisible() {
  for (const track of state.filtered) {
    state.selectedPaths.add(track.path);
  }
  renderTable();
  updateBatchBar();
}

function setBatchLoading(isLoading) {
  batchLoading.classList.toggle("hidden", !isLoading);
  applySelectedBtn.disabled = isLoading;
  applySelectedBtn.textContent = isLoading ? "Applying..." : "Apply to Selected";
}

function formValuesToTags(form) {
  const tags = {};
  for (const field of editableFields) {
    const el = form.elements.namedItem(field);
    if (!el) {
      continue;
    }
    const value = el.value.trim();
    if (value.length === 0) {
      continue;
    }
    tags[field] = value;
  }
  return tags;
}

function populateEditorForm(tags) {
  for (const field of editableFields) {
    const input = trackForm.elements.namedItem(field);
    if (!input) {
      continue;
    }
    input.value = tags[field] || "";
  }
}

async function loadIndex() {
  const data = await api("api/index");
  state.index = data;
  state.filtered = [...data];
  renderTable();
  updateBatchBar();
}

async function openEditor(path) {
  const data = await api(`api/track?path=${encodeURIComponent(path)}`);
  state.activePath = data.path;
  editorPath.textContent = data.path;
  populateEditorForm(data.tags || {});
  editorPanel.classList.remove("hidden");
}

async function saveTrack(event) {
  event.preventDefault();
  if (!state.activePath) {
    return;
  }
  const tags = formValuesToTags(trackForm);
  await api("api/track", {
    method: "PATCH",
    body: JSON.stringify({
      path: state.activePath,
      tags,
    }),
  });
  showMessage("Track updated.");
  await loadIndex();
}

async function applyBatch(event) {
  event.preventDefault();
  const tags = formValuesToTags(batchForm);
  if (Object.keys(tags).length === 0) {
    showMessage("No batch fields set.", true);
    return;
  }

  setBatchLoading(true);
  try {
    await api("api/batch", {
      method: "POST",
      body: JSON.stringify({
        paths: Array.from(state.selectedPaths),
        tags,
      }),
    });
    showMessage("Batch update complete.");
    batchForm.reset();
    await loadIndex();
  } finally {
    setBatchLoading(false);
  }
}

async function triggerRescan() {
  const result = await api("api/rescan", { method: "POST" });
  if (result.ok) {
    showMessage("Owntone rescan triggered.");
    return;
  }
  showMessage(`Rescan failed: ${result.message || "unknown error"}`, true);
}

tracksBody.addEventListener("click", async (event) => {
  const target = event.target;
  if (target.matches("input[type='checkbox'][data-path]")) {
    const path = target.dataset.path;
    if (target.checked) {
      state.selectedPaths.add(path);
    } else {
      state.selectedPaths.delete(path);
    }
    updateBatchBar();
    event.stopPropagation();
    return;
  }

  const row = target.closest("tr[data-path]");
  if (!row) {
    return;
  }
  try {
    await openEditor(row.dataset.path);
  } catch (err) {
    sendFrontendLog({
      level: "error",
      source: "openEditor",
      message: errorToString(err),
    });
    showMessage(err.message, true);
  }
});

searchInput.addEventListener("input", applySearch);
selectVisibleBtn.addEventListener("click", selectAllVisible);
trackForm.addEventListener("submit", async (event) => {
  try {
    await saveTrack(event);
  } catch (err) {
    sendFrontendLog({
      level: "error",
      source: "saveTrack",
      message: errorToString(err),
    });
    showMessage(err.message, true);
  }
});
batchForm.addEventListener("submit", async (event) => {
  try {
    await applyBatch(event);
  } catch (err) {
    sendFrontendLog({
      level: "error",
      source: "applyBatch",
      message: errorToString(err),
    });
    showMessage(err.message, true);
  }
});
rescanBtn.addEventListener("click", async () => {
  try {
    await triggerRescan();
  } catch (err) {
    sendFrontendLog({
      level: "error",
      source: "rescan",
      message: errorToString(err),
    });
    showMessage(err.message, true);
  }
});
closeEditorBtn.addEventListener("click", () => {
  editorPanel.classList.add("hidden");
  state.activePath = null;
});

loadIndex().catch((err) => {
  sendFrontendLog({
    level: "error",
    source: "loadIndex",
    message: errorToString(err),
  });
  showMessage(`Failed to load index: ${err.message}`, true);
});

window.addEventListener("error", (event) => {
  sendFrontendLog({
    level: "error",
    source: "window.onerror",
    message: event.message || "Unhandled window error",
    stack: event.error?.stack || null,
    context: {
      filename: event.filename || null,
      lineno: event.lineno || null,
      colno: event.colno || null,
    },
  });
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  sendFrontendLog({
    level: "error",
    source: "unhandledrejection",
    message: errorToString(reason),
    stack: reason?.stack || null,
  });
});
