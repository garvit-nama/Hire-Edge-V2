// ── api helpers ───────────────────────────────────────────────────────────────
function getBase() {
  const el = document.getElementById('backendUrl');
  if (el?.value?.trim()) return el.value.trim().replace(/\/$/, '');
  if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
    return 'http://localhost:5000';
  }
  return 'https://hireedge-backend.onrender.com';
}

function getHeaders() {
  const headers = {};
  if (S.token) headers['Authorization'] = `Bearer ${S.token}`;
  return headers;
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
async function login(email, password) {
  try {
    const r = await fetch(getBase() + '/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Login failed');
    
    S.token = d.token;
    S.user = d.user;
    localStorage.setItem('token', d.token);
    localStorage.setItem('user', JSON.stringify(d.user));
    toast('🔑', 'Logged in!');
    return true;
  } catch (e) {
    toast('❌', e.message);
    return false;
  }
}

async function register(email, password) {
  try {
    const r = await fetch(getBase() + '/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Registration failed');
    toast('✅', 'Registered! Please login.');
    return true;
  } catch (e) {
    toast('❌', e.message);
    return false;
  }
}

function logout() {
  S.token = null;
  S.user = null;
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  window.location.href = 'index.html';
}

// ── health check ───────────────────────────────────────────────────────────────
async function checkHealth() {
  const dot = document.getElementById('apiDot');
  const text = document.getElementById('apiText');
  if (!dot || !text) return;
  try {
    const r = await fetch(getBase() + '/health', { signal: AbortSignal.timeout(4000) });
    const data = await r.json();
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
  } catch {
    dot.className = 'api-dot off';
    text.textContent = 'Backend Offline';
  }
}

async function fetchModels() {
  try {
    const r = await fetch(getBase() + '/models');
    const data = await r.json();
    if (!data.models?.length) return;
    const chips = document.getElementById('modelChips');
    if (!chips) return;
    chips.innerHTML = data.models.map((m, i) =>
      `<button class="mchip${i === 0 ? ' active' : ''}" data-model="${m.id}" onclick="pickModel(this)">
        ${m.label} ${m.tag ? `<span class="mchip-tag">${m.tag}</span>` : ''}
       </button>`
    ).join('');
    if (S) S.model = data.models[0].id;
  } catch { /* keep defaults */ }
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
    const data = await r.json();
    if (!r.ok) {
      if (r.status === 403) {
        showFreemiumLimit();
        throw new Error(data.error);
      }
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

function showFreemiumLimit() {
  resetUI();
  showUpgradeModal();
}

function showUpgradeModal() {
  // Remove existing modal if any
  const existing = document.getElementById('upgradeModal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'upgradeModal';
  modal.className = 'upgrade-modal';
  modal.innerHTML = `
    <div class="upgrade-overlay"></div>
    <div class="upgrade-box">
      <div class="upgrade-header">
        <span class="upgrade-icon">🔒</span>
        <h2>Free Limit Reached</h2>
      </div>
      <div class="upgrade-body">
        <p>You've used all <strong>3 free analyses</strong>.</p>
        <p>Upgrade to Premium for:</p>
        <ul class="upgrade-perks">
          <li>✓ Unlimited analyses</li>
          <li>✓ Priority processing</li>
          <li>✓ Advanced insights</li>
          <li>✓ Export to PDF</li>
        </ul>
      </div>
      <div class="upgrade-actions">
        <button class="upgrade-btn-primary" onclick="simulateUpgrade()">
          <span>Upgrade to Premium</span>
          <span class="upgrade-price">$9.99/mo</span>
        </button>
        <button class="upgrade-btn-secondary" onclick="closeUpgradeModal()">
          Maybe Later
        </button>
      </div>
    </div>
  `;

  // Add styles
  const style = document.createElement('style');
  style.id = 'upgradeModalStyle';
  style.textContent = `
    .upgrade-modal {
      position: fixed;
      top: 0; left: 0;
      width: 100%; height: 100%;
      z-index: 9999;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .upgrade-overlay {
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      background: rgba(0, 0, 0, 0.8);
      backdrop-filter: blur(4px);
    }
    .upgrade-box {
      position: relative;
      background: linear-gradient(135deg, rgba(30, 30, 40, 0.98), rgba(20, 20, 30, 0.98));
      border: 1px solid rgba(168, 85, 247, 0.3);
      border-radius: 24px;
      padding: 40px;
      max-width: 420px;
      width: 90%;
      box-shadow: 0 25px 80px rgba(168, 85, 247, 0.2);
      animation: upgradeSlideIn 0.3s ease-out;
    }
    @keyframes upgradeSlideIn {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .upgrade-header {
      text-align: center;
      margin-bottom: 24px;
    }
    .upgrade-icon {
      font-size: 3rem;
      display: block;
      margin-bottom: 12px;
    }
    .upgrade-header h2 {
      font-family: 'Familjen Grotesk', sans-serif;
      font-size: 1.8rem;
      font-weight: 700;
      color: white;
      margin: 0;
    }
    .upgrade-body {
      color: rgba(255, 255, 255, 0.8);
      font-size: 0.95rem;
      line-height: 1.6;
      margin-bottom: 28px;
    }
    .upgrade-body strong {
      color: #f472b6;
    }
    .upgrade-perks {
      list-style: none;
      padding: 0;
      margin: 16px 0 0 0;
      background: rgba(168, 85, 247, 0.1);
      border-radius: 12px;
      padding: 20px;
    }
    .upgrade-perks li {
      padding: 6px 0;
      color: #a78bfa;
    }
    .upgrade-actions {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .upgrade-btn-primary {
      background: linear-gradient(135deg, #a855f7, #c084fc);
      color: white;
      border: none;
      border-radius: 12px;
      padding: 16px 24px;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .upgrade-btn-primary:hover {
      transform: translateY(-2px);
      box-shadow: 0 10px 30px rgba(168, 85, 247, 0.4);
    }
    .upgrade-price {
      background: rgba(0, 0, 0, 0.2);
      padding: 4px 12px;
      border-radius: 20px;
      font-size: 0.85rem;
    }
    .upgrade-btn-secondary {
      background: transparent;
      color: rgba(255, 255, 255, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 12px;
      padding: 14px 24px;
      font-size: 0.95rem;
      cursor: pointer;
      transition: all 0.2s;
    }
    .upgrade-btn-secondary:hover {
      border-color: rgba(255, 255, 255, 0.4);
      color: rgba(255, 255, 255, 0.8);
    }
  `;

  document.body.appendChild(style);
  document.body.appendChild(modal);
}

function closeUpgradeModal() {
  const modal = document.getElementById('upgradeModal');
  const style = document.getElementById('upgradeModalStyle');
  if (modal) modal.remove();
  if (style) style.remove();
}

function simulateUpgrade() {
  const btn = document.querySelector('.upgrade-btn-primary');
  btn.disabled = true;
  btn.innerHTML = `<span>Upgrading...</span>`;

  fetch(getBase() + '/api/upgrade', {
    method: 'POST',
    headers: getHeaders()
  })
  .then(r => {
    if (!r.ok) throw new Error('Upgrade request failed');
    return r.json();
  })
  .then(data => {
    if (S.user) {
      S.user.tier = 'premium';
      localStorage.setItem('user', JSON.stringify(S.user));
    }
    btn.innerHTML = `<span>✓ Upgrade Complete!</span>`;
    btn.style.background = 'linear-gradient(135deg, #22c55e, #4ade80)';

    setTimeout(() => {
      closeUpgradeModal();
      toast('🎉', 'Welcome to Premium! Unlimited analyses unlocked.');
      updateUserUI();
      if (document.getElementById('resultsWrap').classList.contains('show')) {
        window.location.reload();
      }
    }, 1000);
  })
  .catch(err => {
    btn.disabled = false;
    btn.innerHTML = `<span>Upgrade to Premium</span>`;
    toast('❌', 'Upgrade failed: ' + err.message);
  });
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
      
      // Store metadata for freemium truncation
      if (data.is_truncated !== undefined) {
        S.jobMetadata = S.jobMetadata || {};
        S.jobMetadata.is_truncated = data.is_truncated;
      }
      
      if (data.status === 'complete') {
        clearInterval(S.pollInterval);
        S.results = data.results;
        S.jobMetadata = S.jobMetadata || {};
        S.jobMetadata.is_truncated = data.is_truncated || false;
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
    const r = await fetch(getBase() + `/status/${jid}`, { headers: getHeaders() });
    const d = await r.json();
    updateAgentBoard(d);
    
    // Phase 3-4: Store metadata for freemium truncation
    if (d.is_truncated !== undefined) {
      S.jobMetadata = S.jobMetadata || {};
      S.jobMetadata.is_truncated = d.is_truncated;
    }
    
    if (d.status === 'complete') { 
      clearInterval(S.pollInterval); 
      S.results = d.results;
      S.jobMetadata = S.jobMetadata || {};
      S.jobMetadata.is_truncated = d.is_truncated || false;
      renderResults(); 
    }
    else if (d.status === 'error') { 
      clearInterval(S.pollInterval); 
      showError(d.message); 
    }
  } catch (e) { 
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
    const r = await fetch(getBase() + `/status/${jid}`, { headers: getHeaders() });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed to load report');
    
    updateAgentBoard(d);
    
    // Store metadata for freemium truncation
    if (d.is_truncated !== undefined) {
      S.jobMetadata = S.jobMetadata || {};
      S.jobMetadata.is_truncated = d.is_truncated;
    }
    
    if (d.status === 'complete') {
      S.results = d.results;
      S.jobMetadata = S.jobMetadata || {};
      S.jobMetadata.is_truncated = d.is_truncated || false;
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
    const r = await fetch(getBase() + `/report/${S.jobId}`, { headers: getHeaders() });
    if (!r.ok) { toast('❌', 'Download failed: ' + (r.status === 401 ? 'Unauthorized' : 'Server error')); return; }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'hireedge_report.txt';
    a.click();
    toast('📥', 'Downloaded!');
  } catch (e) { toast('❌', 'Download failed: ' + e.message); }
}
