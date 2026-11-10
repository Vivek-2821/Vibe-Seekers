"""
Authentication routes: login, register, logout, password reset
Friction-free signup with rate limiting and bot honeypot protection (OTP verification removed).
"""
import re
import time
import secrets
from collections import defaultdict
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.email import send_password_reset_email
from app import db

auth_bp = Blueprint('auth', __name__)

# In-memory IP rate limiters
_signup_attempts = defaultdict(list)
_login_attempts = defaultdict(list)


def _get_client_ip():
    """Retrieve client IP address considering proxy headers."""
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


def _is_rate_limited(ip, tracker, max_attempts, window_seconds):
    """Sliding-window IP rate limiter."""
    now = time.time()
    tracker[ip] = [t for t in tracker[ip] if now - t < window_seconds]
    if len(tracker[ip]) >= max_attempts:
        return True
    tracker[ip].append(now)
    return False


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        # Honeypot bot protection
        if request.form.get('website_url'):
            return redirect(url_for('main.index'))

        # Rate limiting: max 10 login attempts per 15 minutes per IP
        ip = _get_client_ip()
        if _is_rate_limited(ip, _login_attempts, max_attempts=10, window_seconds=900):
            flash('Too many login attempts. Please wait a few minutes before trying again.', 'error')
            return render_template('auth/login.html', title='Login – Vibe Seekers')

        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'
        
        user = User.query.filter(db.func.lower(User.email) == email).first()
        
        if not user or not user.check_password(password):
            flash('Invalid email or password.', 'error')
            return render_template('auth/login.html', title='Login – Vibe Seekers')
        
        if user.is_blocked:
            flash('Your account has been suspended. Please contact support.', 'error')
            return render_template('auth/login.html', title='Login – Vibe Seekers')

        # Auto-verify any legacy unverified user (email verification removed)
        if not user.is_email_verified:
            user.is_email_verified = True
            db.session.commit()
        
        login_user(user, remember=remember)
        flash(f'Welcome back, {user.name.split()[0]}!', 'success')
        
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        if user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('main.index'))
    
    return render_template('auth/login.html', title='Login – Vibe Seekers')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        # Honeypot bot protection
        if request.form.get('website_url'):
            return redirect(url_for('main.index'))

        # Rate limiting: max 5 signups per hour per IP
        ip = _get_client_ip()
        if _is_rate_limited(ip, _signup_attempts, max_attempts=5, window_seconds=3600):
            flash('Too many signup attempts from this device. Please wait a bit before trying again.', 'error')
            return render_template('auth/register.html', title='Create Account – Vibe Seekers')

        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        
        errors = []
        if not name:
            errors.append('Full name is required.')
        if not email or not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
            errors.append('A valid email address is required.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters long.')
        if password != confirm:
            errors.append('Passwords do not match.')

        existing_user = User.query.filter(db.func.lower(User.email) == email).first()
        if existing_user:
            # If from old incomplete OTP verification attempt, activate and log in directly
            if not existing_user.is_email_verified or existing_user.otp_code:
                existing_user.name = name
                existing_user.phone = phone
                existing_user.is_email_verified = True
                existing_user.otp_code = None
                existing_user.otp_expiry = None
                existing_user.set_password(password)
                db.session.commit()
                login_user(existing_user)
                flash(f'🎉 Welcome to Vibe Seekers, {existing_user.name.split()[0]}! Your account is active.', 'success')
                return redirect(url_for('main.index'))
            else:
                flash('An account with this email address already exists. Please log in.', 'error')
                return render_template('auth/register.html', title='Create Account – Vibe Seekers')
        
        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('auth/register.html', title='Create Account – Vibe Seekers')

        # Create active verified user directly (no OTP, no pending status)
        user = User(
            name=name,
            email=email,
            phone=phone,
            is_email_verified=True
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash(f'🎉 Welcome to Vibe Seekers, {user.name.split()[0]}! Your account is ready.', 'success')
        return redirect(url_for('main.index'))
    
    return render_template('auth/register.html', title='Create Account – Vibe Seekers')


@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    """Bypassed: Redirect any legacy verification links straight to store."""
    return redirect(url_for('main.index'))


@auth_bp.route('/resend-otp', methods=['POST'])
def resend_otp():
    """Bypassed: Redirect any legacy OTP resend calls straight to store."""
    return redirect(url_for('main.index'))


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You\'ve been logged out. See you soon!', 'info')
    return redirect(url_for('main.index'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        # Honeypot bot protection
        if request.form.get('website_url'):
            return redirect(url_for('main.index'))

        email = request.form.get('email', '').strip().lower()
        user = User.query.filter(db.func.lower(User.email) == email).first()
        
        flash('If that email is registered, you will receive a password reset link shortly.', 'info')
        
        if user:
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expiry = datetime.utcnow() + timedelta(minutes=30)
            db.session.commit()
            
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            try:
                send_password_reset_email(user.email, reset_url, user.name)
            except Exception as e:
                print(f"⚠️ Error sending password reset email: {e}")
        
        return redirect(url_for('auth.login'))
    
    return render_template('auth/forgot_password.html', title='Reset Password – Vibe Seekers')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or (user.reset_token_expiry and user.reset_token_expiry < datetime.utcnow()):
        flash('This reset link is invalid or has expired (valid for 30 minutes).', 'error')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        
        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return render_template('auth/reset_password.html', token=token)
        
        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('auth/reset_password.html', token=token)
        
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        
        flash('Password reset successfully! Please log in with your new password.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password.html', token=token, title='Reset Password – Vibe Seekers')
