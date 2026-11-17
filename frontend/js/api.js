// ── api helpers ───────────────────────────────────────────────────────────────
function getBase() {
  const el = document.getElementById('backendUrl');
  if (el?.value?.trim()) return el.value.trim().replace(/\/$/, '');
  // Vercel / build-time injection: window.BACKEND_URL or window.__BACKEND_URL__
  if (typeof window !== 'undefined') {
    if (window.BACKEND_URL?.trim()) return window.BACKEND_URL.trim().replace(/\/$/, '');
    if (window.__BACKEND_URL__?.trim()) return window.__BACKEND_URL__.trim().replace(/\/$/, '');
  }
  // Dev override via localStorage (e.g. localStorage.setItem('backendUrl','http://localhost:5000'))
  try {
    const ls = localStorage.getItem('backendUrl');
    if (ls?.trim()) return ls.trim().replace(/\/$/, '');
  } catch {}
  if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
    return 'http://localhost:5000';
  }
  // If not on Vercel (e.g. Flask directly serves frontend at same origin), use same origin
  if (!location.hostname.includes('vercel.app') && !location.hostname.includes('netlify.app')) {
    // Heuristic: same-origin backend — use current origin (works for Render serving frontend/)
    // Only if origin is not a static-only host. Keep fallback to Render URL if origin is file://
    if (location.protocol.startsWith('http')) return location.origin.replace(/\/$/, '');
  }
  return 'https://hireedge-backend.onrender.com';
}

function getHeaders() {
  const headers = {};
  if (S.token) headers['Authorization'] = `Bearer ${S.token}`;
  return headers;
}

/**
 * Safely parse JSON — throws a human-readable error if server returned HTML
 * (e.g. Vercel 404 page, Render wake-up interstitial, Flask 404 HTML) instead of JSON.
 * Prevents:  Unexpected token '<', "<!doctype ..." is not valid JSON
 */
async function parseJsonSafe(response) {
  const ct = (response.headers.get('content-type') || '').toLowerCase();
  const isJson = ct.includes('application/json') || ct.includes('json');

  if (!isJson) {
    const text = await response.text();
    const trimmed = text.trim();
    if (/^<!doctype/i.test(trimmed) || /^<html/i.test(trimmed)) {
      throw new Error(
        `Server returned HTML instead of JSON (HTTP ${response.status} ${response.statusText}). ` +
        `Backend at ${getBase()} may be offline, sleeping, or URL is wrong. Try again in 20-30s (Render cold start) or check backendUrl.`
      );
    }
    // Not HTML but also not JSON — try to parse as JSON anyway for tolerance
    if (trimmed) {
      try { return JSON.parse(trimmed); } catch {}
    }
    throw new Error(trimmed.slice(0, 400) || `Unexpected response (HTTP ${response.status} ${response.statusText})`);
  }

  // Content-Type says JSON — but body may still be HTML on some mis-configured 404s
  const text = await response.text();
  if (/^<!doctype/i.test(text.trim()) || /^<html/i.test(text.trim())) {
    throw new Error(
      `Server returned HTML instead of JSON (HTTP ${response.status}). Backend at ${getBase()} is not serving the API.`
    );
  }
  try {
    return text ? JSON.parse(text) : {};
  } catch (e) {
    throw new Error(`Invalid JSON response: ${e.message}`);
  }
}

let toastT;
function toast(icon, msg) {
  const el = document.getElementById('toast');
  if (!el) return console.log(icon, msg);
  document.getElementById('toastIcon').textContent = icon;
  document.getElementById('toastMsg').textContent = msg;
  el.classList.add('show');
  clearTimeout(toastT);
  toastT = setTimeout(() => el.classList.remove('show'), 3500);
}

// ── auth ───────────────────────────────────────────────────────────────────────
function _formatApiError(d, fallback) {
  // Prefer structured 503 detail (DB unavailable) over raw psycopg2
  if (d && d.error === 'Database unavailable') {
    return `${d.error}: ${d.detail || ''} ${d.hint ? '(' + d.hint + ')' : ''}`.trim();
  }
  if (d && d.detail) return `${d.error}: ${d.detail}`;
  return (d && d.error) || fallback;
}

async function login(email, password) {
  try {
    const r = await fetch(getBase() + '/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
      signal: AbortSignal.timeout(10000)
    });
    const d = await parseJsonSafe(r);
    if (!r.ok) {
      // Special UX for DB-down 503
      if (r.status === 503 || (d && d.error === 'Database unavailable')) {
        throw new Error(_formatApiError(d, 'Database unavailable — check DATABASE_URL (Supabase pooler) or set ALLOW_SQLITE_FALLBACK=true'));
      }
      throw new Error(_formatApiError(d, 'Login failed'));
    }
    
    S.token = d.token;
    S.user = d.user;
    localStorage.setItem('token', d.token);
    localStorage.setItem('user', JSON.stringify(d.user));
    toast('🔑', 'Logged in!');
    try { updateFooterUI(); } catch {}
    return true;
  } catch (e) {
    console.warn('[login]', e.message);
    toast('❌', e.message);
    return false;
  }
}

async function register(email, password) {
  try {
    const r = await fetch(getBase() + '/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
      signal: AbortSignal.timeout(10000)
    });
    const d = await parseJsonSafe(r);
    if (!r.ok) {
      if (r.status === 503 || (d && d.error === 'Database unavailable')) {
        throw new Error(_formatApiError(d, 'Database unavailable — check DATABASE_URL (Supabase pooler) or set ALLOW_SQLITE_FALLBACK=true'));
      }
      throw new Error(_formatApiError(d, 'Registration failed'));
    }
    toast('✅', 'Registered! Please login.');
    return true;
  } catch (e) {
    console.warn('[register]', e.message);
    toast('❌', e.message);
    return false;
  }
}

function logout() {
  if (!confirm('Are you sure you want to log out?')) return;

  S.token = null;
  S.user = null;
  localStorage.removeItem('token');
  localStorage.removeItem('user');

  try { updateFooterUI(); } catch {}
  toast('👋', 'Logged out');
  window.location.href = 'index.html';
}

// ── health check ───────────────────────────────────────────────────────────────
async function checkHealth() {
  const dot = document.getElementById('apiDot');
  const text = document.getElementById('apiText');
  if (!dot || !text) return;
  try {
    const r = await fetch(getBase() + '/health', { signal: AbortSignal.timeout(15000) });
    const data = await parseJsonSafe(r);
    // Health now returns 503 when DB down — still JSON, handle explicitly
    if (data.db === false) {
      dot.className = 'api-dot off';
      text.textContent = 'DB Offline';
      console.warn('[health] DB offline:', data.db_error, 'hint:', data.hint, 'host:', data.db_host);
      // Still fetch models if Groq ok, but surface DB issue
      if (data.db_error) toast('⚠️', 'Database offline: ' + (data.db_error.slice(0,80)));
      return;
    }
    if (!r.ok) throw new Error(data.error || 'Health check failed');
    if (data.is_mock) {
      dot.className = 'api-dot on';
      text.textContent = 'Simulated Mode';
    } else if (data.groq) {
      dot.className = 'api-dot on';
      text.textContent = 'Groq Connected';
    } else {
      dot.className = 'api-dot off';
      text.textContent = 'API Key Missing';
    }
    fetchModels();
  } catch (e) {
    dot.className = 'api-dot off';
    // Distinguish HTML-vs-offline for debuggability (console)
    if (String(e.message).includes('HTML instead of JSON')) console.warn('[health]', e.message);
    else if (String(e.message).includes('Database unavailable')) console.warn('[health] DB unavailable:', e.message);
    text.textContent = 'Backend Offline';
  }
}

async function fetchModels() {
  try {
    const r = await fetch(getBase() + '/models', { signal: AbortSignal.timeout(5000) });
    const data = await parseJsonSafe(r);
    if (!data.models?.length) return;
    const chips = document.getElementById('modelChips');
    if (!chips) return;
    chips.innerHTML = data.models.map((m, i) =>
      `<button class="mchip${i === 0 ? ' active' : ''}" data-model="${m.id}" onclick="pickModel(this)">
        ${m.label} ${m.tag ? `<span class="mchip-tag">${m.tag}</span>` : ''}
       </button>`
    ).join('');
    if (S) S.model = data.models[0].id;
  } catch (e) {
    if (String(e.message).includes('HTML instead of JSON')) console.warn('[models]', e.message);
    /* keep defaults */
  }
}

// ── submit analysis ────────────────────────────────────────────────────────────
async function startAnalysis() {
  if (!S.token) {
    toast('🔒', 'Please login to start an analysis.');
    setTimeout(() => window.location.href = 'login.html', 1500);
    return;
  }

  const role = document.getElementById('jobRole').value.trim();
  if (!S.candidateFile || !S.hrFile || !role) return;

  document.getElementById('inputPanel').style.opacity = '0.4';
  document.getElementById('inputPanel').style.pointerEvents = 'none';
  document.getElementById('runBtn').disabled = true;
  document.getElementById('errorStrip').classList.remove('show');
  document.getElementById('progressPanel').classList.add('show');
  setStep(3);
  buildAgentBoard([]);

  const fd = new FormData();
  fd.append('candidate_pdf', S.candidateFile);
  fd.append('hr_pdf', S.hrFile);
  fd.append('job_role', role);
  fd.append('model', S.model);

  try {
    const r = await fetch(getBase() + '/analyse', { 
      method: 'POST', 
      headers: getHeaders(), // Note: FormData handles its own multipart boundary, so just add Auth
      body: fd 
    });
    const data = await parseJsonSafe(r);
    if (!r.ok) {
      throw new Error(data.error || 'Server error'); 
    }
    S.jobId = data.job_id;
    toast('🚀', 'Agents running…');
    
    // Phase 5: Initialize WebSocket for real-time updates
    initWebSocket();
    if (wsConnected && socket) {
      socket.emit('join_job', { job_id: S.jobId });
    } else {
      // Fallback to polling if WebSocket not available
      S.pollInterval = setInterval(() => pollJob(S.jobId), 2000);
    }
    
    pollJob(S.jobId);
  } catch (e) {
    showError(e.message);
  }
}

// ── WebSocket Real-time Updates (Phase 5) ──────────────────────────────────────
let socket = null;
let wsConnected = false;

function initWebSocket() {
  if (socket) return; // Already initialized
  
  try {
    // Import socket.io client dynamically or load from CDN
    // For now, check if Socket.IO is available globally
    if (typeof io === 'undefined') {
      console.warn('Socket.IO client not available. Will use polling fallback.');
      return;
    }
    
    socket = io(getBase(), {
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 5,
      transports: ['websocket', 'polling']
    });
    
    socket.on('connect', () => {
      wsConnected = true;
      console.log('✅ WebSocket connected');
      if (S.jobId) {
        socket.emit('join_job', { job_id: S.jobId });
      }
    });
    
    socket.on('disconnect', () => {
      wsConnected = false;
      console.log('❌ WebSocket disconnected, falling back to polling');
      // Fallback to polling if disconnected
      if (S.jobId && !S.pollInterval) {
        S.pollInterval = setInterval(() => pollJob(S.jobId), 2000);
      }
    });
    
    socket.on('job_status', (data) => {
      // Real-time job status update
      console.log('📍 WebSocket job_status:', data);
      updateAgentBoard(data);
      
      if (data.status === 'complete') {
        clearInterval(S.pollInterval);
        S.results = data.results;
        renderResults();
      } else if (data.status === 'error') {
        clearInterval(S.pollInterval);
        showError(data.message);
      }
    });
    
    socket.on('error', (err) => {
      console.error('WebSocket error:', err);
      // Fallback to polling
      if (!S.pollInterval && S.jobId) {
        S.pollInterval = setInterval(() => pollJob(S.jobId), 2000);
      }
    });
    
  } catch (err) {
    console.error('Failed to initialize WebSocket:', err);
  }
}

// ── SSE stream / Polling ────────────────────────────────────────────────────────
// (pollJob provides fallback when WebSocket is unavailable or disconnects)

async function pollJob(jid) {
  try {
    const r = await fetch(getBase() + `/status/${jid}`, { headers: getHeaders(), signal: AbortSignal.timeout(10000) });
    const d = await parseJsonSafe(r);
    if (!r.ok) throw new Error(d.error || `Status ${r.status}`);
    updateAgentBoard(d);
    
    if (d.status === 'complete') { 
      clearInterval(S.pollInterval); 
      S.results = d.results;
      renderResults(); 
    }
    else if (d.status === 'error') { 
      clearInterval(S.pollInterval); 
      showError(d.message); 
    }
  } catch (e) { 
    // Don't kill polling on transient HTML error — surface but keep retrying once
    if (String(e.message).includes('HTML instead of JSON')) {
      console.warn('[pollJob] HTML response — backend may be waking up:', e.message);
      // keep polling; show gentle message once
      // showError would reset UI and clear interval; avoid that for transient wake-up
      return;
    }
    clearInterval(S.pollInterval); 
    showError('Lost connection: ' + e.message); 
  }
}

// ── load archived job ────────────────────────────────────────────────────────
async function loadArchivedJob(jid) {
  if (!S.token) {
    toast('🔒', 'Please login to view this report.');
    setTimeout(() => window.location.href = 'login.html', 1500);
    return;
  }

  document.getElementById('inputPanel').style.opacity = '0.4';
  document.getElementById('inputPanel').style.pointerEvents = 'none';
  document.getElementById('runBtn').disabled = true;
  document.getElementById('errorStrip').classList.remove('show');
  document.getElementById('progressPanel').classList.add('show');
  setStep(3);
  buildAgentBoard([]);

  S.jobId = jid;
  
  try {
    const r = await fetch(getBase() + `/status/${jid}`, { headers: getHeaders(), signal: AbortSignal.timeout(10000) });
    const d = await parseJsonSafe(r);
    if (!r.ok) throw new Error(d.error || 'Failed to load report');
    
    updateAgentBoard(d);
    
    if (d.status === 'complete') {
      S.results = d.results;
      renderResults();
    } else if (d.status === 'error') {
      showError(d.message);
    } else {
      initWebSocket();
      if (wsConnected && socket) {
        socket.emit('join_job', { job_id: S.jobId });
      } else {
        S.pollInterval = setInterval(() => pollJob(S.jobId), 2000);
      }
      pollJob(S.jobId);
    }
  } catch (e) {
    showError(e.message);
  }
}

// ── download report ────────────────────────────────────────────────────────────
async function downloadReport() {
  if (!S.token) {
    toast('🔒', 'Please login to download reports.');
    setTimeout(() => window.location.href = 'login.html', 1500);
    return;
  }
  if (!S.jobId) return;
  try {
    const r = await fetch(getBase() + `/report/${S.jobId}`, { headers: getHeaders(), signal: AbortSignal.timeout(15000) });
    // Report endpoint returns text/plain on success, JSON on error
    const ct = (r.headers.get('content-type') || '').toLowerCase();
    if (!r.ok) {
      // Error body should be JSON; handle HTML case
      let msg = `Server error (${r.status})`;
      if (ct.includes('json')) {
        try { const j = await r.json(); msg = j.error || msg; } catch {}
      } else {
        const txt = await r.text();
        if (/^<!doctype/i.test(txt.trim()) || /^<html/i.test(txt.trim())) {
          msg = `Backend returned HTML (HTTP ${r.status}). Check backend URL ${getBase()}`;
        } else if (txt.trim()) msg = txt.trim().slice(0,200);
      }
      toast('❌', 'Download failed: ' + msg);
      return;
    }
    if (ct.includes('json')) {
      // Unexpected JSON on success path (e.g., error disguised as 200)
      const j = await parseJsonSafe(r);
      if (j.error) { toast('❌', j.error); return; }
    }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'hireedge_report.txt';
    a.click();
    toast('📥', 'Downloaded!');
  } catch (e) { toast('❌', 'Download failed: ' + e.message); }
}
