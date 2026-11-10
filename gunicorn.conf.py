"""
Gunicorn configuration file
Automatically binds to Render's dynamic $PORT to prevent 502 Bad Gateway errors.
"""
import os

port = os.environ.get('PORT', '10000')
bind = f"0.0.0.0:{port}"
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
threads = 4
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"

