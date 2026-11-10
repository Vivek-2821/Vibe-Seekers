"""
Utility helpers for Vibe Seekers
"""
import os
import re
import uuid
import secrets
from datetime import datetime
from PIL import Image
from flask import current_app
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_image(file, subfolder='products', max_size=(1200, 1200)):
    """
    Save an uploaded image:
    1. If CLOUDINARY_URL is configured, upload to Cloudinary (persistent across Render redeploys).
    2. Fallback to local /static/uploads/{subfolder}/ when Cloudinary is not configured.
    Returns the image URL (https://res.cloudinary.com/... or /static/uploads/...).
    """
    if not file or not allowed_file(file.filename):
        return None

    cloudinary_url = os.environ.get('CLOUDINARY_URL', '').strip().strip("'\"")
    if cloudinary_url:
        try:
            import cloudinary
            import cloudinary.uploader
            
            # Configure cloudinary
            cloudinary.config(cloudinary_url=cloudinary_url, secure=True)
            
            # Reset stream position
            file.seek(0)
            upload_result = cloudinary.uploader.upload(
                file,
                folder=f"vibeseekers/{subfolder}",
                resource_type="image",
                overwrite=True
            )
            secure_url = upload_result.get('secure_url')
            if secure_url:
                print(f"☁️ [CLOUDINARY UPLOAD SUCCESS] Saved to {secure_url}")
                return secure_url
        except Exception as e:
            print(f"⚠️ [CLOUDINARY UPLOAD FAILED, FALLING BACK TO LOCAL]: {e}")
            try:
                file.seek(0)
            except Exception:
                pass

    # Local fallback
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    
    img = Image.open(file)
    img = img.convert('RGB')
    img.thumbnail(max_size, Image.LANCZOS)
    img.save(filepath, quality=88, optimize=True)
    
    return f'/static/uploads/{subfolder}/{filename}'


def slugify(text):
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'[^\w-]', '', text)
    text = re.sub(r'-+', '-', text)
    return text


def get_site_url():
    """Returns the canonical public site URL, defaulting to https://vibeseekers.in."""
    url = os.environ.get('SITE_URL', 'https://vibeseekers.in').strip().rstrip('/')
    return url if url else 'https://vibeseekers.in'


def generate_order_number():
    """Generate a unique order number."""
    ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    rand = secrets.token_hex(3).upper()
    return f'VS-{ts}-{rand}'


def format_price(amount):
    """Format price in Indian Rupees."""
    return f'₹{amount:,.2f}'


def generate_reset_token():
    return secrets.token_urlsafe(32)


def deduct_product_stock(product, quantity, size=None):
    """
    Deduct ordered quantity from total product stock and specific size stock if size is provided.
    Keeps total stock in sync with size stocks.
    """
    if not product or quantity <= 0:
        return
    if size:
        from app.models import ProductSize
        ps = ProductSize.query.filter_by(product_id=product.id).filter(
            ProductSize.size.ilike(str(size).strip())
        ).first()
        if ps:
            ps.stock = max(0, int(ps.stock or 0) - quantity)
    product.stock = max(0, int(product.stock or 0) - quantity)


def restore_product_stock(product, quantity, size=None):
    """
    Restore quantity to total product stock and specific size stock if size is provided.
    """
    if not product or quantity <= 0:
        return
    if size:
        from app.models import ProductSize
        ps = ProductSize.query.filter_by(product_id=product.id).filter(
            ProductSize.size.ilike(str(size).strip())
        ).first()
        if ps:
            ps.stock = int(ps.stock or 0) + quantity
    product.stock = int(product.stock or 0) + quantity


# ─── Simple In-Memory Rate Limiter ───────────────────────────────────────────
import time
from collections import defaultdict

class InMemoryRateLimiter:
    def __init__(self):
        self._requests = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        timestamps = self._requests[key]
        cutoff = now - window_seconds
        valid_ts = [t for t in timestamps if t > cutoff]
        self._requests[key] = valid_ts
        if len(valid_ts) >= max_requests:
            return False
        self._requests[key].append(now)
        return True

rate_limiter = InMemoryRateLimiter()

def check_rate_limit(key_prefix: str, max_requests: int = 15, window_seconds: int = 300):
    """
    Checks rate limit based on client IP.
    Returns True if allowed, False if exceeded.
    """
    from flask import request
    forwarded = request.headers.get('X-Forwarded-For')
    ip = forwarded.split(',')[0].strip() if forwarded else (request.remote_addr or '127.0.0.1')
    key = f"{key_prefix}:{ip}"
    return rate_limiter.is_allowed(key, max_requests, window_seconds)

