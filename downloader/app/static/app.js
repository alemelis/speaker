'use strict';

const form          = document.getElementById('dl-form');
const playlistCheck = document.getElementById('playlist-check');
const titleField    = document.getElementById('title-field');
const delayField    = document.getElementById('delay-field');
const fetchBtn      = document.getElementById('fetch-btn');
const submitBtn     = document.getElementById('submit-btn');

const trackSection  = document.getElementById('track-section');
const trackCount    = document.getElementById('track-count');
const trackList     = document.getElementById('track-list');
const selAllBtn     = document.getElementById('sel-all-btn');
const selNoneBtn    = document.getElementById('sel-none-btn');
const dlSelectedBtn = document.getElementById('dl-selected-btn');

const progressSection = document.getElementById('progress-section');
const spinner         = document.getElementById('spinner');
const barWrap         = document.getElementById('bar-wrap');
const barFill         = document.getElementById('bar-fill');
const barLabel        = document.getElementById('bar-label');

const errorLog  = document.getElementById('error-log');
const statusMsg = document.getElementById('status-msg');

// --- Mode toggle ---

playlistCheck.addEventListener('change', () => {
  const pl = playlistCheck.checked;
  titleField.classList.toggle('hidden', pl);
  delayField.classList.toggle('hidden', pl);
  fetchBtn.classList.toggle('hidden', !pl);
  submitBtn.classList.toggle('hidden', pl);
  trackSection.classList.add('hidden');
  resetFeedback();
});

// --- Fetch playlist ---

fetchBtn.addEventListener('click', async () => {
  const url = document.getElementById('url-input').value.trim();
  if (!url) return;

  resetFeedback();
  fetchBtn.disabled = true;
  fetchBtn.textContent = 'Fetching...';

  try {
    const res = await fetch('api/playlist-info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      const text = await res.text();
      showError(text);
      return;
    }
    const { entries } = await res.json();
    renderTrackList(entries);
    trackSection.classList.remove('hidden');
  } catch (err) {
    showError(err.message);
  } finally {
    fetchBtn.disabled = false;
    fetchBtn.textContent = 'Fetch tracks';
  }
});

function renderTrackList(entries) {
  trackList.innerHTML = '';
  entries.forEach(({ index, title }) => {
    const li = document.createElement('li');
    li.innerHTML = `<label><input type="checkbox" value="${index}" checked> ${title}</label>`;
    trackList.appendChild(li);
  });
  trackCount.textContent = `${entries.length} tracks`;
}

selAllBtn.addEventListener('click',  () => trackList.querySelectorAll('input').forEach(cb => cb.checked = true));
selNoneBtn.addEventListener('click', () => trackList.querySelectorAll('input').forEach(cb => cb.checked = false));

// --- Download selected (playlist) ---

dlSelectedBtn.addEventListener('click', () => {
  const selected = [...trackList.querySelectorAll('input:checked')].map(cb => +cb.value);
  if (!selected.length) return;
  startDownload({ playlist: true, selected_items: selected, total: selected.length });
});

// --- Download single track ---

form.addEventListener('submit', e => {
  e.preventDefault();
  startDownload({ playlist: false, selected_items: [], total: 1 });
});

// --- Core download ---

async function startDownload({ playlist, selected_items, total }) {
  resetFeedback();
  showProgress(playlist, total);

  const body = {
    url:            document.getElementById('url-input').value.trim(),
    artist:         document.getElementById('artist-input').value.trim(),
    album:          document.getElementById('album-input').value.trim(),
    title:          document.getElementById('title-input').value.trim(),
    playlist,
    delay:          parseInt(document.getElementById('delay-input').value, 10) || 0,
    selected_items,
  };

  let res;
  try {
    res = await fetch('api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (err) {
    hideProgress();
    showError(err.message);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    // SSE events are separated by double newlines
    const parts = buf.split('\n\n');
    buf = parts.pop();

    for (const part of parts) {
      const eventLine = part.match(/^event: (\w+)/m);
      const dataLine  = part.match(/^data: (.*)/m);
      if (!eventLine) continue;
      const event = eventLine[1];
      const data  = dataLine ? dataLine[1] : '';

      if (event === 'progress') {
        const { done: d, total: t } = JSON.parse(data);
        updateBar(d, t);
      } else if (event === 'done') {
        hideProgress();
        showStatus('ok', 'Done.');
        return;
      } else if (event === 'error') {
        hideProgress();
        showError(data);
        return;
      }
      // 'log' events are intentionally ignored — shown only on error
    }
  }

  hideProgress();
}

// --- Progress UI ---

function showProgress(playlist, total) {
  progressSection.classList.remove('hidden');
  if (playlist) {
    spinner.classList.add('hidden');
    barWrap.classList.remove('hidden');
    updateBar(0, total);
  } else {
    barWrap.classList.add('hidden');
    spinner.classList.remove('hidden');
  }
}

function hideProgress() {
  progressSection.classList.add('hidden');
}

function updateBar(done, total) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  barFill.style.width = pct + '%';
  barLabel.textContent = `${done} / ${total}`;
}

// --- Feedback helpers ---

function showStatus(type, msg) {
  statusMsg.textContent = msg;
  statusMsg.className = `status ${type}`;
  statusMsg.classList.remove('hidden');
}

function showError(log) {
  errorLog.textContent = log;
  errorLog.classList.remove('hidden');
  showStatus('error', 'Download failed.');
}

function resetFeedback() {
  progressSection.classList.add('hidden');
  errorLog.classList.add('hidden');
  statusMsg.classList.add('hidden');
  errorLog.textContent = '';
}
