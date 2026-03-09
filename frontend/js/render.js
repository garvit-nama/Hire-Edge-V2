const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function parseSections(text) {
  const lines = text.split('\n');
  const secs  = [];
  let cur     = null;
  for (let i = 0; i < lines.length; i++) {
    const raw  = lines[i];
    const trim = raw.trim();
    const next = (lines[i+1] || '').trim();
    const isHeader =
      /^[A-Z][A-Z\s\/&\-\(\)0-9#:]+$/.test(trim) &&
      trim.length >= 4 && trim.length <= 72 && !/^[\-=]+$/.test(trim);
    const hasUnderline = /^[=\-]{3,}/.test(next);
    if (isHeader) {
      if (cur) secs.push(cur);
      cur = { title: trim.replace(/:$/, ''), lines: [] };
      if (hasUnderline) i++;
    } else if (cur) { cur.lines.push(raw); }
    else {
      if (!secs.length) secs.push({ title: null, lines: [] });
      secs[secs.length-1].lines.push(raw);
    }
  }
  if (cur) secs.push(cur);
  return secs.filter(s => s.lines.some(l => l.trim()));
}

function parseKV(lines) {
  const kvs = []; let k = null, v = [];
  for (const line of lines) {
    const m = line.match(/^([A-Za-z][^:\n]{1,50}):\s*(.*)$/);
    if (m && !line.startsWith(' ') && !line.startsWith('-')) {
      if (k) kvs.push({ k, v: v.join(' ').trim() });
      k = m[1].trim(); v = [m[2]];
    } else if (k) { v.push(line.trim()); }
  }
  if (k) kvs.push({ k, v: v.join(' ').trim() });
  return kvs.filter(x => x.v);
}

function parseNumbered(lines) {
  return lines.map(l => l.match(/^\s*(\d+)[\.\)]\s+(.+)$/)).filter(Boolean).map(m => m[2].trim());
}

function renderReportCard(id, text) {
  const el   = document.getElementById(id);
  const secs = parseSections(text);
  let   html = '<div class="rpt-card">';
  secs.forEach(sec => {
    if (!sec.title) {
      const c = sec.lines.join('\n').trim();
      if (c) html += `<div class="rpt-section"><div class="rpt-plain">${esc(c)}</div></div>`;
      return;
    }
    const body     = sec.lines.filter(l => l.trim());
    const numbered = parseNumbered(body);
    const kvs      = parseKV(body);
    const isScore  = /SCORE/i.test(sec.title);
    html += `<div class="rpt-section"><div class="rpt-sec-title">${esc(sec.title)}</div>`;
    if (isScore) {
      const sm = body.join(' ').match(/(\d+(?:\.\d+)?)\s*\/\s*10/);
      if (sm) html += `<div class="score-chip">⭐ ${sm[1]} / 10</div>`;
      const rest = body.join('\n').replace(/.*\d+\/10.*/gi,'').trim();
      if (rest) html += `<div class="rpt-plain" style="font-size:13px">${esc(rest)}</div>`;
    } else if (numbered.length >= 2) {
      html += `<div class="rpt-list">`;
      numbered.forEach((item,i) => {
        html += `<div class="rpt-li"><div class="rpt-li-n">${i+1}</div><div class="rpt-li-txt">${esc(item)}</div></div>`;
      });
      html += `</div>`;
    } else if (kvs.length >= 2) {
      html += `<div class="rpt-kv-grid">`;
      kvs.forEach(kv => { html += `<div class="rpt-kv"><div class="rpt-key">${esc(kv.k)}</div><div class="rpt-val">${esc(kv.v)}</div></div>`; });
      html += `</div>`;
    } else {
      html += `<div class="rpt-plain">${esc(body.join('\n'))}</div>`;
    }
    html += `</div>`;
  });
  html += '</div>';
  el.innerHTML = html || `<div class="rpt-card"><div class="rpt-section"><div class="rpt-plain">${esc(text)}</div></div></div>`;
}

function renderRoadmap(id, text) {
  const el = document.getElementById(id);
  const phases = [
    { key:'DAY 1',    label:'Day 1 — First Contact',     col:'var(--orange)' },
    { key:'WEEK 1',   label:'Week 1 — Build Visibility', col:'var(--lime)' },
    { key:'WEEK 2',   label:'Week 2 — Credibility',      col:'var(--purple)' },
    { key:'MONTH 1',  label:'Month 1 — Convert',         col:'var(--orange)' },
    { key:'FOLLOW',   label:'Follow-Up Rules',           col:'var(--text2)' },
    { key:'PARALLEL', label:'Parallel Strategies',       col:'var(--text2)' },
  ];
  const lines  = text.split('\n');
  const blocks = {};
  let active   = '__pre__'; blocks[active] = [];
  lines.forEach(line => {
    const upper = line.trim().toUpperCase();
    const hit   = phases.find(p => upper.startsWith(p.key));
    if (hit && line.trim().length < 65) {
      active = hit.key; if (!blocks[active]) blocks[active] = [];
    } else { if (!blocks[active]) blocks[active] = []; blocks[active].push(line); }
  });
  let html = `<div class="rpt-card"><div class="rpt-section"><div class="timeline">`;
  phases.forEach(ph => {
    const blk = blocks[ph.key];
    if (!blk || !blk.some(l => l.trim())) return;
    html += `<div class="tl-item">
      <div class="tl-phase" style="color:${ph.col}">${ph.label}</div>
      <div class="tl-body">${esc(blk.join('\n').trim())}</div>
    </div>`;
  });
  html += `</div></div></div>`;
  el.innerHTML = html;
}

function renderMessages(id, text) {
  const el    = document.getElementById(id);
  const types = [
    { n:'01', label:'LinkedIn Connection Request',    pat:/1\.\s*LINKEDIN CONNECTION REQUEST[\s\S]*?\n([\s\S]*?)(?=\n2\.)/i,  full:true },
    { n:'02', label:'LinkedIn DM — After Connecting', pat:/2\.\s*LINKEDIN DM.*?CONNECT[\s\S]*?\n([\s\S]*?)(?=\n3\.)/i },
    { n:'03', label:'Follow-Up DM (Day 5)',           pat:/3\.\s*LINKEDIN DM.*?FOLLOW[\s\S]*?\n([\s\S]*?)(?=\n4\.)/i },
    { n:'04', label:'Cold Email — First Outreach',    pat:/4\.\s*COLD EMAIL[\s\S]*?\n([\s\S]*?)(?=\n5\.)/i, email:true },
    { n:'05', label:'Follow-Up Email (Day 5)',        pat:/5\.\s*FOLLOW.UP EMAIL[\s\S]*?\n([\s\S]*?)(?=\n6\.)/i, email:true },
    { n:'06', label:'Final Email — Day 14',           pat:/6\.\s*FINAL EMAIL[\s\S]*?\n([\s\S]*?)(?=\n7\.)/i, email:true },
    { n:'07', label:'Referral Request',               pat:/7\.\s*REFERRAL[\s\S]*?\n([\s\S]*?)(?=\n8\.)/i },
    { n:'08', label:'Thank You Message',              pat:/8\.\s*THANK YOU[\s\S]*?\n([\s\S]*?)(?=\nTONE|$)/i },
  ];
  let html = `<div class="msg-grid">`;
  types.forEach(t => {
    const m   = text.match(t.pat);
    const raw = m ? m[1].trim() : null;
    let subject = '', body = raw;
    if (t.email && raw) {
      const sm = raw.match(/Subject Line:?\s*\n?([^\n]+)/i);
      if (sm) { subject = sm[1].trim(); body = raw.replace(/Subject Line:?[^\n]*\n?/i,'').replace(/^Body[^:]*:\s*/i,'').trim(); }
    }
    const bodyText = body || '— Not extracted. Please re-run analysis.';
    html += `<div class="msg-card${t.full?' full':''}">
      <div class="msg-top"><span class="msg-label">${t.n}</span><button class="msg-copy" onclick="copyMsg(this)">Copy</button></div>
      <div class="msg-type">${t.label}</div>`;
    if (subject) html += `<div class="msg-subj-row"><span class="msg-subj-lbl">Subject</span><span class="msg-subj-val">${esc(subject)}</span></div>`;
    html += `<div class="msg-body">${esc(bodyText)}</div></div>`;
  });
  const tm = text.match(/TONE GUIDE[\s\S]*?\n([\s\S]*?)$/i);
  if (tm) html += `<div class="msg-card"><div class="msg-top"><span class="msg-label">Tone</span></div><div class="msg-type">Tone Guide</div><div class="msg-body">${esc(tm[1].trim())}</div></div>`;
  html += `</div>`;
  el.innerHTML = html;
}

function renderScorecard(id, text) {
  const el = document.getElementById(id);
  const metrics = [
    { name:'Connection Acceptance', pat:/CONNECTION ACCEPTANCE.*?(\d+)%[\s\S]*?Why:\s*([^\n]+)/i, col:'var(--orange)' },
    { name:'DM Reply',              pat:/DM REPLY.*?(\d+)%[\s\S]*?Why:\s*([^\n]+)/i,             col:'var(--lime)' },
    { name:'Email Reply',           pat:/EMAIL REPLY.*?(\d+)%[\s\S]*?Why:\s*([^\n]+)/i,          col:'var(--purple)' },
    { name:'Interview Conversion',  pat:/INTERVIEW CONVERSION.*?(\d+)%[\s\S]*?Why:\s*([^\n]+)/i, col:'var(--orange)' },
  ];
  const strM      = text.match(/OVERALL CAMPAIGN STRENGTH:\s*\[?(\w+)\]?/i);
  const str       = strM ? strM[1].toLowerCase() : null;
  const strClass  = { weak:'sw', moderate:'sm', strong:'ss', elite:'se' }[str] || 'sw';
  let html = `<div class="scorecard-grid">`;
  let mHtml = '';
  metrics.forEach(m => {
    const mx = text.match(m.pat);
    if (!mx) return;
    mHtml += `<div class="metric-line">
      <div class="ml-pct" style="color:${m.col}">${mx[1]}%</div>
      <div class="ml-info"><div class="ml-name">${m.name}</div><div class="ml-why">${esc(mx[2])}</div></div>
    </div>`;
  });
  if (mHtml) {
    const badge = str ? `<div class="strength-pill ${strClass}">Campaign: ${str.charAt(0).toUpperCase()+str.slice(1)}</div>` : '';
    html += `<div class="sc-block"><div class="sc-block-title">Probability Scores</div>${badge}${mHtml}</div>`;
  }
  const xlist = (pat) => {
    const m = text.match(pat);
    if (!m) return null;
    return m[1].split('\n').filter(l=>/^\s*\d+[\.\)]/.test(l)).map(l=>l.replace(/^\s*\d+[\.\)]\s*/,'').trim()).filter(Boolean);
  };
  const working = xlist(/TOP 3 THINGS WORKING.*?\n([\s\S]*?)(?=TOP 3 RISKS|$)/i);
  if (working?.length) {
    html += `<div class="sc-block"><div class="sc-block-title">Working in Your Favour</div><div class="rpt-list">`;
    working.forEach((item,i) => { html += `<div class="rpt-li"><div class="rpt-li-n" style="background:rgba(61,220,132,0.1);border-color:rgba(61,220,132,0.3);color:var(--success)">${i+1}</div><div class="rpt-li-txt">${esc(item)}</div></div>`; });
    html += `</div></div>`;
  }
  const risks = xlist(/TOP 3 RISKS[\s\S]*?\n([\s\S]*?)(?=WHAT WOULD|$)/i);
  if (risks?.length) {
    html += `<div class="sc-block"><div class="sc-block-title">Top Risks</div><div class="rpt-list">`;
    risks.forEach((item,i) => { html += `<div class="rpt-li"><div class="rpt-li-n" style="background:rgba(255,92,26,0.1);border-color:rgba(255,92,26,0.3);color:var(--orange)">${i+1}</div><div class="rpt-li-txt">${esc(item)}</div></div>`; });
    html += `</div></div>`;
  }
  const boost = xlist(/WHAT WOULD INCREASE[\s\S]*?\n([\s\S]*?)(?=DAILY|$)/i);
  if (boost?.length) {
    html += `<div class="sc-block"><div class="sc-block-title">What Adds +30% Success</div><div class="rpt-list">`;
    boost.forEach((item,i) => { html += `<div class="rpt-li"><div class="rpt-li-n" style="background:rgba(197,241,53,0.1);border-color:rgba(197,241,53,0.3);color:var(--lime)">${i+1}</div><div class="rpt-li-txt">${esc(item)}</div></div>`; });
    html += `</div></div>`;
  }
  const ckM  = text.match(/DAILY CHECKLIST[\s\S]*?\n([\s\S]*?)(?=FINAL ADVICE|$)/i);
  const adM  = text.match(/FINAL ADVICE[\s\S]*?\n([\s\S]*?)$/i);
  if (ckM || adM) {
    html += `<div class="sc-block full"><div class="sc-block-title">Daily Checklist & Final Advice</div>`;
    if (ckM) html += `<div class="rpt-plain" style="margin-bottom:18px">${esc(ckM[1].trim())}</div>`;
    if (adM) html += `<div class="rpt-plain">${esc(adM[1].trim())}</div>`;
    html += `</div>`;
  }
  if (!mHtml && !working && !risks) html += `<div class="sc-block full"><div class="sc-block-title">Success Scorecard</div><div class="rpt-plain">${esc(text)}</div></div>`;
  html += `</div>`;
  el.innerHTML = html;
}

function parseScores(text) {
  const ex = p => { const m = text.match(p); return m ? parseInt(m[1]) : null; };
  const s1 = ex(/CONNECTION ACCEPTANCE.*?(\d+)/i);
  const s2 = ex(/DM REPLY.*?(\d+)/i);
  const s3 = ex(/INTERVIEW CONVERSION.*?(\d+)/i);
  if (s1) { document.getElementById('sc1').textContent = s1+'%'; document.getElementById('sb1').style.width = s1+'%'; }
  if (s2) { document.getElementById('sc2').textContent = s2+'%'; document.getElementById('sb2').style.width = s2+'%'; }
  if (s3) { document.getElementById('sc3').textContent = s3+'%'; document.getElementById('sb3').style.width = s3+'%'; }
}

function renderResults() {
  setStep(4);
  const r = S.results;
  renderReportCard('tp-candidate', r.a1 || '');
  renderReportCard('tp-hr',        r.a2 || '');
  renderReportCard('tp-alignment', r.a3 || '');
  renderRoadmap   ('tp-roadmap',   r.a4 || '');
  renderMessages  ('tp-messages',  r.a5 || '');
  renderScorecard ('tp-scorecard', r.a6 || '');
  parseScores(r.a6 || '');
  document.getElementById('resultsWrap').classList.add('show');
  document.getElementById('resultsWrap').scrollIntoView({ behavior:'smooth' });
  toast('✅', 'Report ready!');
}

function copyMsg(btn) {
  const card = btn.closest('.msg-card');
  const subj = card.querySelector('.msg-subj-val');
  const body = card.querySelector('.msg-body');
  let txt = '';
  if (subj) txt += 'Subject: ' + subj.textContent + '\n\n';
  if (body) txt += body.textContent;
  navigator.clipboard.writeText(txt).then(() => {
    btn.textContent = '✓ Copied'; btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
  });
}
