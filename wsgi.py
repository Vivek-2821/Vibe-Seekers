"""
WSGI entry point for Gunicorn on Render.
Usage: gunicorn wsgi:app
"""
import os
from app import create_app

app = create_app()

# WhiteNoise integration for high-performance static file serving in production
try:
    from whitenoise import WhiteNoise
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    app.wsgi_app = WhiteNoise(app.wsgi_app, root=static_dir, prefix='static/')
except ImportError:
    pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

