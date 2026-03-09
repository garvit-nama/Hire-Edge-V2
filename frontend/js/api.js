// ── helpers ────────────────────────────────────────────────────────────────────
function getBase() {
  return (document.getElementById('backendUrl').value || 'http://localhost:5000').trim().replace(/\/$/, '');
}

let toastT;
function toast(icon, msg) {
  const el = document.getElementById('toast');
  document.getElementById('toastIcon').textContent = icon;
  document.getElementById('toastMsg').textContent  = msg;
  el.classList.add('show');
  clearTimeout(toastT);
  toastT = setTimeout(() => el.classList.remove('show'), 3500);
}

// ── health check ───────────────────────────────────────────────────────────────
async function checkHealth() {
  const dot  = document.getElementById('apiDot');
  const text = document.getElementById('apiText');
  try {
    const r    = await fetch(getBase() + '/health', { signal: AbortSignal.timeout(4000) });
    const data = await r.json();
    if (data.groq) {
      dot.className  = 'api-dot on';
      text.textContent = 'Groq Connected';
    } else {
      dot.className  = 'api-dot off';
      text.textContent = 'API Key Missing';
    }
    fetchModels();
  } catch {
    dot.className  = 'api-dot off';
    text.textContent = 'Backend Offline';
  }
}

async function fetchModels() {
  try {
    const r    = await fetch(getBase() + '/models');
    const data = await r.json();
    if (!data.models?.length) return;
    const chips = document.getElementById('modelChips');
    chips.innerHTML = data.models.map((m, i) =>
      `<button class="mchip${i===0?' active':''}" data-model="${m.id}" onclick="pickModel(this)">
        ${m.label} ${m.tag ? `<span class="mchip-tag">${m.tag}</span>` : ''}
       </button>`
    ).join('');
    S.model = data.models[0].id;
  } catch { /* keep defaults */ }
}

// ── submit analysis ────────────────────────────────────────────────────────────
async function startAnalysis() {
  const role = document.getElementById('jobRole').value.trim();
  if (!S.candidateFile || !S.hrFile || !role) return;

  document.getElementById('inputPanel').style.opacity       = '0.4';
  document.getElementById('inputPanel').style.pointerEvents = 'none';
  document.getElementById('runBtn').disabled = true;
  document.getElementById('errorStrip').classList.remove('show');
  document.getElementById('progressPanel').classList.add('show');
  setStep(3);
  buildAgentBoard([]);

  const fd = new FormData();
  fd.append('candidate_pdf', S.candidateFile);
  fd.append('hr_pdf',        S.hrFile);
  fd.append('job_role',      role);
  fd.append('model',         S.model);

  try {
    const r = await fetch(getBase() + '/analyse', { method: 'POST', body: fd });
    if (!r.ok) { const e = await r.json(); throw new Error(e.error || 'Server error'); }
    const data = await r.json();
    S.jobId = data.job_id;
    toast('🚀', 'Agents running…');
    openSSE(S.jobId);
  } catch(e) {
    showError(e.message);
  }
}

// ── SSE stream ─────────────────────────────────────────────────────────────────
function openSSE(jid) {
  const es = new EventSource(getBase() + `/stream/${jid}`);
  es.onmessage = e => {
    const d = JSON.parse(e.data);
    updateAgentBoard(d);
    if (d.status === 'complete') { es.close(); S.results = d.results; renderResults(); }
    else if (d.status === 'error') { es.close(); showError(d.message || 'Unknown error'); }
  };
  es.onerror = () => { es.close(); S.pollInterval = setInterval(() => pollJob(jid), 2000); };
}

async function pollJob(jid) {
  try {
    const r = await fetch(getBase() + `/status/${jid}`);
    const d = await r.json();
    updateAgentBoard(d);
    if (d.status === 'complete') { clearInterval(S.pollInterval); S.results = d.results; renderResults(); }
    else if (d.status === 'error') { clearInterval(S.pollInterval); showError(d.message); }
  } catch(e) { clearInterval(S.pollInterval); showError('Lost connection: ' + e.message); }
}

// ── download report ────────────────────────────────────────────────────────────
async function downloadReport() {
  if (!S.jobId) return;
  try {
    const r    = await fetch(getBase() + `/report/${S.jobId}`);
    const blob = await r.blob();
    const a    = document.createElement('a');
    a.href     = URL.createObjectURL(blob);
    a.download = 'hireedge_report.txt';
    a.click();
    toast('📥', 'Downloaded!');
  } catch(e) { toast('❌', 'Download failed: ' + e.message); }
}
