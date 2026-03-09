# gunicorn.conf.py — Production WSGI server config
# Usage: gunicorn -c gunicorn.conf.py app:app

bind             = "0.0.0.0:5000"
workers          = 4            # 2 × CPU cores + 1  (adjust for your server)
worker_class     = "sync"
timeout          = 300          # 5 min — LLM agents can take time
keepalive        = 5
max_requests     = 500          # Recycle workers to prevent memory leaks
max_requests_jitter = 50
accesslog        = "-"          # stdout
errorlog         = "-"          # stdout
loglevel         = "info"
forwarded_allow_ips = "*"       # if behind nginx/reverse proxy
