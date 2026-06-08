const S = {
  candidateFile: null,
  hrFile:        null,
  model:         'llama-3.3-70b-versatile',
  jobId:         null,
  pollInterval:  null,
  results:       {},
  user:          JSON.parse(localStorage.getItem('user')) || null,
  token:         localStorage.getItem('token') || null
};
