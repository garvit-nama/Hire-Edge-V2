let _user = null;
try { _user = JSON.parse(localStorage.getItem('user')); } catch { _user = null; }

const S = {
  candidateFile: null,
  hrFile:        null,
  model:         'openai/gpt-oss-120b',
  jobId:         null,
  pollInterval:  null,
  results:       {},
  user:          _user,
  token:         localStorage.getItem('token') || null
};
