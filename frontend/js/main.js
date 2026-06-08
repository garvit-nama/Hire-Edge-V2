// ── Scroll to app ──────────────────────────────────────────────────────────────
function scrollToApp() {
  document.getElementById('appShell').scrollIntoView({ behavior: 'smooth' });
}

function resetToHome() {
  document.getElementById('heroSection').scrollIntoView({ behavior: 'smooth' });
}

// ── File handling ──────────────────────────────────────────────────────────────
function handleDrop(type, input) {
  const file = input.files[0];
  if (!file) return;
  if (type === 'candidate') {
    S.candidateFile = file;
    document.getElementById('dropCandidate').classList.add('done');
    document.getElementById('statusCand').textContent = '✓ ' + file.name;
    document.getElementById('iconCand').innerHTML = `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`;
  } else {
    S.hrFile = file;
    document.getElementById('dropHR').classList.add('done');
    document.getElementById('statusHR').textContent = '✓ ' + file.name;
    document.getElementById('iconHR').innerHTML = `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`;
  }
  checkReady();
}

function checkReady() {
  const role  = document.getElementById('jobRole').value.trim();
  const ready = S.candidateFile && S.hrFile && role.length > 2;
  document.getElementById('runBtn').disabled = !ready;
  if (ready) setStep(2);
}

function pickModel(el) {
  document.querySelectorAll('.mchip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  S.model = el.dataset.model;
}

// Drag & drop events
['dropCandidate','dropHR'].forEach(id => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener('dragover',  e => { e.preventDefault(); el.classList.add('drag'); });
  el.addEventListener('dragleave', () => el.classList.remove('drag'));
  el.addEventListener('drop', e => {
    e.preventDefault(); el.classList.remove('drag');
    const file = e.dataTransfer.files[0];
    if (file?.type === 'application/pdf') {
      const type  = id === 'dropCandidate' ? 'candidate' : 'hr';
      const input = el.querySelector('input');
      const dt    = new DataTransfer(); dt.items.add(file); input.files = dt.files;
      handleDrop(type, input);
    }
  });
});

// ── Step management ────────────────────────────────────────────────────────────
function setStep(n) {
  for (let i = 1; i <= 4; i++) {
    const sn = document.getElementById('sn' + i);
    if (!sn) continue;
    sn.className = 'step-node' + (i < n ? ' done' : i === n ? ' active' : '');
    const ring = sn.querySelector('.sn-ring');
    if (i < n && ring) ring.textContent = '✓';
  }
  for (let i = 1; i <= 3; i++) {
    const sw = document.getElementById('sw' + i);
    if (sw) sw.className = 'step-wire' + (i < n ? ' done' : '');
  }
}

// ── Agent board ────────────────────────────────────────────────────────────────
const AGENT_DEFAULTS = [
  {id:'a1',name:'Candidate Analyser',  label:'Parsing resume & extracting selling points'},
  {id:'a2',name:'HR Profiler',         label:'Building hiring manager intelligence model'},
  {id:'a3',name:'Alignment Strategist',label:'Matching candidate strengths to HR priorities'},
  {id:'a4',name:'Outreach Architect',  label:'Designing Day / Week / Month roadmap'},
  {id:'a5',name:'Message Copywriter',  label:'Crafting personalized message suite'},
  {id:'a6',name:'Success Analyst',     label:'Scoring campaign & building action plan'},
];

function buildAgentBoard(agents) {
  const board = document.getElementById('agentBoard');
  const items = agents.length ? agents : AGENT_DEFAULTS;
  board.innerHTML = items.map((a, i) => `
    <div class="agent-card queued" id="ac-${a.id}">
      <div class="ac-num" id="an-${a.id}">${String(i+1).padStart(2,'0')}</div>
      <div class="ac-info">
        <div class="ac-name">${a.name || AGENT_DEFAULTS[i]?.name || ''}</div>
        <div class="ac-label" id="al-${a.id}">${a.label || 'Queued'}</div>
      </div>
      <span class="ac-badge bq" id="ab-${a.id}">Queued</span>
    </div>
  `).join('');
}

function updateAgentBoard(data) {
  if (!data.agents) return;
  if (!document.getElementById('ac-a1')) buildAgentBoard(data.agents);

  data.agents.forEach((a, i) => {
    const card  = document.getElementById(`ac-${a.id}`);
    const num   = document.getElementById(`an-${a.id}`);
    const label = document.getElementById(`al-${a.id}`);
    const badge = document.getElementById(`ab-${a.id}`);
    if (!card) return;
    card.className = `agent-card ${a.status}`;
    if (a.status === 'running') {
      num.innerHTML     = '<span class="spin-ring"></span>';
      label.textContent = a.label || 'Processing…';
      badge.className   = 'ac-badge brun'; badge.textContent = 'Running';
    } else if (a.status === 'done') {
      num.textContent   = String(i+1).padStart(2,'0');
      label.textContent = 'Complete';
      badge.className   = 'ac-badge bdn'; badge.textContent = '✓ Done';
    } else if (a.status === 'error') {
      num.textContent   = '✕';
      label.textContent = a.error || 'Failed';
      badge.className   = 'ac-badge berr'; badge.textContent = 'Error';
    }
  });

  const pct = Math.round(((data.progress || 0) / 6) * 100);
  document.getElementById('progFill').style.width   = pct + '%';
  document.getElementById('progCount').textContent  = `${data.progress || 0} / 6 agents complete`;
  document.getElementById('progPct').textContent    = pct + '%';
}

// ── Tab switching ──────────────────────────────────────────────────────────────
function switchTab(el, id) {
  document.querySelectorAll('.tab').forEach(t  => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById(id).classList.add('active');
}

// ── Error & reset ──────────────────────────────────────────────────────────────
function showError(msg) {
  document.getElementById('errorBody').textContent = msg;
  document.getElementById('errorStrip').classList.add('show');
  document.getElementById('progressPanel').classList.remove('show');
  toast('❌', msg.substring(0, 60));
}

function resetUI() {
  document.getElementById('inputPanel').style.opacity       = '1';
  document.getElementById('inputPanel').style.pointerEvents = 'auto';
  document.getElementById('progressPanel').classList.remove('show');
  document.getElementById('resultsWrap').classList.remove('show');
  document.getElementById('errorStrip').classList.remove('show');
  document.getElementById('agentBoard').innerHTML = '';
  document.getElementById('progFill').style.width = '0%';
  document.getElementById('runBtn').disabled = false;
  S.jobId = null;
  setStep(1);
  if (S.pollInterval) clearInterval(S.pollInterval);
}

// ── User UI ───────────────────────────────────────────────────────────────────
function updateUserUI() {
  const navContainer = document.getElementById('userNav');
  if (!navContainer) return;

  if (S.user) {
    navContainer.innerHTML = `
      <div class="user-pill">
        <span class="user-email">${S.user.email}</span>
        <div class="user-actions">
          <a href="dashboard.html" class="user-link">History</a>
          <button onclick="logout()" class="user-logout">Logout</button>
        </div>
      </div>
    `;
  } else {
    navContainer.innerHTML = `
      <a href="login.html" class="auth-link">Login</a>
      <a href="register.html" class="auth-pill">Sign Up</a>
    `;
  }
}

// ── Init ───────────────────────────────────────────────────────────────────────
checkHealth();
updateUserUI();
setInterval(checkHealth, 20000);
