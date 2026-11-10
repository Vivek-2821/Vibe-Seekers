"""
Centralized Error Handlers for Vibe Seekers
Handles both standard HTML page requests and AJAX/JSON requests.
"""
from flask import render_template, request, jsonify, current_app

def is_ajax_request():
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.is_json or
        'application/json' in request.headers.get('Accept', '')
    )

def register_error_handlers(app):
    @app.errorhandler(400)
    def bad_request(e):
        msg = getattr(e, 'description', 'Bad Request')
        if is_ajax_request():
            return jsonify({'success': False, 'error': str(msg), 'errors': [str(msg)]}), 400
        return render_template('errors/404.html', title='Bad Request – Vibe Seekers'), 400

    @app.errorhandler(403)
    def forbidden(e):
        msg = getattr(e, 'description', 'Access Denied')
        if is_ajax_request():
            return jsonify({'success': False, 'error': str(msg), 'errors': [str(msg)]}), 403
        return render_template('errors/403.html', title='Access Denied – Vibe Seekers'), 403

    @app.errorhandler(404)
    def not_found(e):
        msg = getattr(e, 'description', 'Page Not Found')
        if is_ajax_request():
            return jsonify({'success': False, 'error': str(msg), 'errors': [str(msg)]}), 404
        return render_template('errors/404.html', title='Page Not Found – Vibe Seekers'), 404

    @app.errorhandler(429)
    def ratelimit_handler(e):
        msg = getattr(e, 'description', 'Too many requests. Please try again later.')
        if is_ajax_request():
            return jsonify({'success': False, 'error': str(msg), 'errors': [str(msg)]}), 429
        return render_template('errors/404.html', title='Rate Limited – Vibe Seekers'), 429

    @app.errorhandler(500)
    def server_error(e):
        import traceback
        tb = traceback.format_exc()
        current_app.logger.error(f"500 Internal Server Error:\n{tb}")
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass
        msg = "An internal server error occurred. Please try again."
        if is_ajax_request():
            return jsonify({'success': False, 'error': msg, 'errors': [msg]}), 500
        return render_template('errors/500.html', title='Something Went Wrong – Vibe Seekers'), 500
