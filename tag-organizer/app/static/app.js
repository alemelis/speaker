const listView = document.getElementById("list-view");
const addView = document.getElementById("add-view");
const openAddBtn = document.getElementById("open-add-btn");
const backBtn = document.getElementById("back-btn");
const tagsSearchInput = document.getElementById("tags-search-input");
const tagsBody = document.getElementById("tags-body");
const message = document.getElementById("message");

const addForm = document.getElementById("add-form");
const tagIdInput = document.getElementById("tag-id-input");
const tapBtn = document.getElementById("tap-btn");
const tapStatus = document.getElementById("tap-status");
const kindSelect = document.getElementById("kind-select");
const searchInput = document.getElementById("search-input");
const searchBtn = document.getElementById("search-btn");
const resultsList = document.getElementById("results-list");
const queryTextInput = document.getElementById("query-text-input");
const queryPreview = document.getElementById("query-preview");

// --- Tap / scan flow ---
let tapPollInterval = null;

function stopTapping() {
  if (tapPollInterval) {
    clearInterval(tapPollInterval);
    tapPollInterval = null;
  }
  tapBtn.textContent = "Tap a tag";
  tapBtn.classList.remove("scanning");
  tapStatus.textContent = "";
}

async function pollUnknownTags() {
  try {
    const ids = await api("api/unknown-tags");
    if (ids.length > 0) {
      tagIdInput.value = ids[0];
      tapStatus.textContent = `Detected: ${ids[0]}`;
      stopTapping();
    }
  } catch (err) {
    tapStatus.textContent = `Error: ${err.message}`;
    stopTapping();
  }
}

tapBtn.addEventListener("click", () => {
  if (tapPollInterval) {
    stopTapping();
    return;
  }
  tagIdInput.value = "";
  tapStatus.textContent = "Tap a tag on the reader…";
  tapBtn.textContent = "Cancel";
  tapBtn.classList.add("scanning");
  tapPollInterval = setInterval(pollUnknownTags, 1500);
});

function showMessage(text, isError = false) {
  message.textContent = text;
  message.classList.toggle("error", isError);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch (err) {
      // Keep default detail.
    }
    throw new Error(detail);
  }
  return response.json();
}

function setView(viewName) {
  const showAdd = viewName === "add";
  if (!showAdd) stopTapping();
  addView.classList.toggle("hidden", !showAdd);
  listView.classList.toggle("hidden", showAdd);
}

function buildPreview() {
  const kind = kindSelect.value;
  const queryText = queryTextInput.value.trim();
  const encoded = encodeURIComponent(queryText).replaceAll("%20", "+");
  if (!queryText) {
    queryPreview.textContent = "";
    return;
  }
  const prefix = kind === "album" ? "albums&query=" : "tracks&query=";
  queryPreview.textContent = `Preview: ${prefix}${encoded}`;
}

let allTags = [];

function renderTags(tags) {
  tagsBody.innerHTML = "";
  for (const item of tags) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.tag_id}</td>
      <td>${item.kind}</td>
      <td>${item.query_text}</td>
      <td class="col-raw">${item.query_raw}</td>
      <td><button type="button" data-delete="${item.tag_id}">Delete</button></td>
    `;
    tagsBody.appendChild(row);
  }
}

function filterTags() {
  const q = (tagsSearchInput.value || "").trim().toLowerCase();
  if (!q) {
    renderTags(allTags);
    return;
  }
  const filtered = allTags.filter(
    (t) =>
      String(t.tag_id).toLowerCase().includes(q) ||
      (t.kind && t.kind.toLowerCase().includes(q)) ||
      (t.query_text && t.query_text.toLowerCase().includes(q)) ||
      (t.query_raw && t.query_raw.toLowerCase().includes(q))
  );
  renderTags(filtered);
}

async function loadTags() {
  allTags = await api("api/tags");
  filterTags();
}

function renderResults(results) {
  resultsList.innerHTML = "";
  if (results.length === 0 && searchInput.value.trim()) {
    const li = document.createElement("li");
    li.className = "no-results";
    li.textContent = "No results";
    resultsList.appendChild(li);
    return;
  }
  for (const result of results) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = result.label;
    btn.addEventListener("click", () => {
      queryTextInput.value = result.query_text;
      buildPreview();
      showMessage("Selected search result.");
    });
    li.appendChild(btn);
    resultsList.appendChild(li);
  }
}

async function runSearch() {
  const q = searchInput.value.trim();
  if (!q) {
    renderResults([]);
    return;
  }
  const params = new URLSearchParams({ kind: kindSelect.value, q });
  const results = await api(`api/search?${params.toString()}`);
  renderResults(results);
}

tagsSearchInput.addEventListener("input", () => {
  filterTags();
});
tagsSearchInput.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    tagsSearchInput.value = "";
    filterTags();
    tagsSearchInput.blur();
  }
});

openAddBtn.addEventListener("click", () => {
  setView("add");
  showMessage("");
});

backBtn.addEventListener("click", async () => {
  setView("list");
  await loadTags();
});

async function doSearch() {
  try {
    await runSearch();
    showMessage("Search complete.");
  } catch (err) {
    showMessage(err.message, true);
  }
}

searchBtn.addEventListener("click", doSearch);

let searchDebounce = null;
searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(doSearch, 350);
});
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    clearTimeout(searchDebounce);
    doSearch();
  }
});

kindSelect.addEventListener("change", buildPreview);
queryTextInput.addEventListener("input", buildPreview);

addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("api/tags", {
      method: "POST",
      body: JSON.stringify({
        tag_id: tagIdInput.value.trim(),
        kind: kindSelect.value,
        query_text: queryTextInput.value.trim(),
      }),
    });
    showMessage("Tag saved.");
    stopTapping();
    addForm.reset();
    queryPreview.textContent = "";
    renderResults([]);
    setView("list");
    await loadTags();
  } catch (err) {
    showMessage(err.message, true);
  }
});

tagsBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-delete]");
  if (!button) {
    return;
  }
  const tagId = button.dataset.delete;
  try {
    await api(`api/tags/${encodeURIComponent(tagId)}`, { method: "DELETE" });
    showMessage(`Deleted tag ${tagId}.`);
    await loadTags();
  } catch (err) {
    showMessage(err.message, true);
  }
});

setView("list");
loadTags().catch((err) => showMessage(err.message, true));
