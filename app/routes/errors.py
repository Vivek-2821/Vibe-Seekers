"""Error handlers"""
from flask import render_template


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html', title='Page Not Found – Vibe Seekers'), 404
    
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html', title='Access Denied – Vibe Seekers'), 403
    
    @app.errorhandler(500)
    def server_error(e):
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass
        return render_template('errors/500.html', title='Something Went Wrong – Vibe Seekers'), 500
