let _user = null;
try { _user = JSON.parse(localStorage.getItem('user')); } catch { _user = null; }

const S = {
  candidateFile: null,
  hrFile:        null,
  model:         'llama-3.3-70b-versatile',
  jobId:         null,
  pollInterval:  null,
  results:       {},
  jobMetadata:   {},  // Phase 3-4: Store is_truncated, analysis_number, etc.
  user:          _user,
  token:         localStorage.getItem('token') || null
};
