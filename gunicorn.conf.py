"""
Gunicorn configuration file for Render deployment.
Tuned for Render Free Tier (512MB RAM) to prevent OOM kills and 502 Bad Gateway errors.
"""
import os

port = os.environ.get('PORT', '10000')
bind = f"0.0.0.0:{port}"
workers = int(os.environ.get('WEB_CONCURRENCY', '1'))
threads = 2
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"


