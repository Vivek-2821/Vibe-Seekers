"""
Vibe Seekers - Flask Application Factory
"""
import os
from dotenv import load_dotenv
from flask import Flask, request, session

# Load environment variables from .env file
load_dotenv()
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()


def create_app(config_name=None):
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    template_dir = os.path.join(base_dir, 'templates')
    static_dir = os.path.join(base_dir, 'static')
    app = Flask(__name__, 
                template_folder=template_dir,
                static_folder=static_dir)
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'vibe-seekers-secret-key-2024-change-in-production')
    
    # Cookie security settings
    is_prod = os.environ.get('FLASK_ENV') == 'production' or not app.debug
    app.config['SESSION_COOKIE_SECURE'] = is_prod
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_SECURE'] = is_prod
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
    
    # Database config (support Render PostgreSQL and local SQLite fallback)
    db_url = os.environ.get('DATABASE_URL')
    if not db_url or not db_url.strip():
        db_url = 'sqlite:///vibe_seekers.db'
    elif db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    if config_name == 'testing':
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    if config_name != 'testing' and db_url.startswith('postgresql'):
        engine_options = {
            'pool_pre_ping': True,
            'pool_recycle': 300,
        }
        if 'sslmode' not in db_url:
            engine_options['connect_args'] = {'sslmode': 'prefer'}
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
    if config_name != 'testing':
        app.config['WTF_CSRF_ENABLED'] = True

    # Trusted Origins and Allowed Hosts for CSRF and CORS
    app.config['WTF_CSRF_TRUSTED_ORIGINS'] = [
        'https://vibeseekers.in',
        'https://www.vibeseekers.in',
        'http://vibeseekers.in',
        'http://www.vibeseekers.in',
        'https://vibe-seekers.onrender.com',
        'http://localhost:5000',
        'http://127.0.0.1:5000',
    ]
    app.config['ALLOWED_HOSTS'] = [
        'vibeseekers.in',
        'www.vibeseekers.in',
        'vibe-seekers.onrender.com',
        'localhost',
        '127.0.0.1',
    ]
    
    # Mail config (update with real SMTP for production)
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@vibeseekers.in')

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    # Ensure upload folders exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'products'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'categories'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'banners'), exist_ok=True)

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.shop import shop_bp
    from app.routes.user import user_bp
    from app.routes.admin import admin_bp
    from app.routes.cart import cart_bp
    from app.routes.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(shop_bp, url_prefix='/shop')
    app.register_blueprint(user_bp, url_prefix='/user')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(cart_bp, url_prefix='/cart')
    app.register_blueprint(api_bp, url_prefix='/api')

    # Register error handlers
    from app.routes.errors import register_error_handlers
    register_error_handlers(app)

    # CSRF error handler returning JSON for AJAX requests
    from flask_wtf.csrf import CSRFError
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        app.logger.warning(f"CSRF Error: {e.description} (Origin: {request.headers.get('Origin')})")
        if (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
            request.is_json or
            'application/json' in request.headers.get('Accept', '')
        ):
            from flask import jsonify
            return jsonify({
                'success': False,
                'error': f"CSRF validation failed ({e.description}). Please refresh the page.",
                'errors': [f"Security token expired ({e.description}). Please refresh the page."]
            }), 400
        from flask import flash, redirect, url_for
        flash("Your security token has expired. Please refresh the page and try again.", "error")
        return redirect(request.referrer or url_for('main.index'))

    # ProxyFix for Render HTTPS / Reverse Proxy Header Support
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    # Context processors
    @app.context_processor
    def inject_globals():
        from app.models import SiteSetting, CartItem
        from flask_login import current_user
        from datetime import datetime as _dt
        
        settings = {}
        try:
            for s in SiteSetting.query.all():
                settings[s.key] = s.value
        except Exception:
            db.session.rollback()
        
        cart_count = 0
        wishlist_count = 0
        try:
            if current_user.is_authenticated and not getattr(current_user, 'is_admin', False):
                cart_count = CartItem.query.filter_by(user_id=current_user.id).count()
                from app.models import Wishlist
                wishlist_count = Wishlist.query.filter_by(user_id=current_user.id).count()
            elif 'cart' in __import__('flask').session:
                cart_count = len(__import__('flask').session.get('cart', {}))
        except Exception:
            db.session.rollback()

        nav_categories = []
        try:
            from app.models import Category
            nav_categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order).all()
        except Exception:
            db.session.rollback()

        return dict(
            site_settings=settings,
            nav_categories=nav_categories,
            cart_count=cart_count,
            wishlist_count=wishlist_count,
            now=_dt.utcnow()
        )

    # Domain Canonicalization & HTTPS Enforcement (Only for GET/HEAD to protect POST data)
    @app.before_request
    def enforce_canonical_and_ssl():
        if config_name == 'testing' or app.debug:
            return None

        # Never redirect POST, PUT, DELETE requests (prevents browser method-switching to GET & dropping payloads)
        if request.method not in ('GET', 'HEAD'):
            return None

        host = (request.host or '').lower().split(':')[0]
        # Ignore localhost / local IP requests during local testing
        if host in ('localhost', '127.0.0.1', 'testserver'):
            return None

        target_host = 'vibeseekers.in'
        needs_host_redirect = host.endswith('onrender.com') or host.startswith('www.')
        proto = request.headers.get('X-Forwarded-Proto', request.scheme).lower()
        needs_ssl_redirect = (proto != 'https')

        if needs_host_redirect or (needs_ssl_redirect and host == target_host):
            qs = f"?{request.query_string.decode('utf-8')}" if request.query_string else ""
            from flask import redirect
            return redirect(f"https://{target_host}{request.path}{qs}", code=301)

    # Performance, Security & CORS Headers
    @app.after_request
    def optimize_response(response):
        # Security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        # CORS Headers for vibeseekers.in and allowed domains
        origin = request.headers.get('Origin')
        allowed_origins = {
            'https://vibeseekers.in',
            'https://www.vibeseekers.in',
            'http://vibeseekers.in',
            'http://www.vibeseekers.in',
            'https://vibe-seekers.onrender.com'
        }
        if origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-CSRFToken, X-Requested-With, Accept'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'

        if request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'public, max-age=86400'
        
        accept_encoding = request.headers.get('Accept-Encoding', '')
        if (
            'gzip' in accept_encoding and
            response.status_code == 200 and
            not response.direct_passthrough and
            'Content-Encoding' not in response.headers and
            response.content_type and
            any(t in response.content_type for t in ['text/', 'application/json', 'application/javascript', 'image/svg+xml'])
        ):
            import gzip
            data = response.get_data()
            if len(data) >= 500:
                compressed = gzip.compress(data, compresslevel=6)
                response.set_data(compressed)
                response.headers['Content-Encoding'] = 'gzip'
                response.headers['Content-Length'] = len(compressed)
        
        return response

    # Auto-initialize database tables and default admin on startup inside create_app()
    if config_name != 'testing':
        with app.app_context():
            from . import models as _models  # Registers all 17 models without shadowing app
            try:
                db.create_all()
            except Exception as e:
                app.logger.error(f"Error in db.create_all(): {e}")
                db.session.rollback()

            # Ensure default admin exists
            try:
                from .models import User
                admin_email = os.environ.get('ADMIN_EMAIL', 'admin@vibeseekers.in')
                admin_pass = os.environ.get('ADMIN_PASSWORD', 'Admin@1234')
                admin = User.query.filter_by(email=admin_email).first()
                if not admin:
                    admin = User(
                        name='Admin',
                        email=admin_email,
                        is_admin=True,
                        is_email_verified=True
                    )
                    admin.set_password(admin_pass)
                    db.session.add(admin)
                    db.session.commit()
                elif not admin.is_admin:
                    admin.is_admin = True
                    admin.is_email_verified = True
                    db.session.commit()
            except Exception as e:
                app.logger.error(f"Error seeding admin: {e}")
                db.session.rollback()

            # Seed default site settings if missing
            try:
                from .models import SiteSetting
                defaults = {
                    'store_name': 'Vibe Seekers',
                    'store_email': os.environ.get('STORE_EMAIL', 'hello@vibeseekers.in'),
                    'store_phone': os.environ.get('STORE_PHONE', '+91 98604 98749'),
                    'store_address': 'India',
                    'announcement_text': '🔥 FREE SHIPPING on orders above ₹999 | Use code VIBE10 for 10% off your first order!',
                    'announcement_active': 'true',
                    'social_instagram': 'https://www.instagram.com/vibe_seekers_09',
                    'social_facebook': '',
                    'social_twitter': '',
                    'social_youtube': '',
                    'upi_id': '',
                    'razorpay_key_id': os.environ.get('RAZORPAY_KEY_ID', ''),
                }
                for key, value in defaults.items():
                    if not SiteSetting.query.filter_by(key=key).first():
                        db.session.add(SiteSetting(key=key, value=value))
                db.session.commit()
            except Exception as e:
                db.session.rollback()

            # Ensure default T-Shirt product and category exist
            try:
                from .models import Category, Product, ProductImage, ProductSize, ProductColor
                cat = Category.query.filter_by(slug='t-shirts').first()
                if not cat:
                    cat = Category(
                        name='T-Shirts',
                        slug='t-shirts',
                        description='Premium streetwear oversized and graphic tees.',
                        image='/static/uploads/categories/cat_tshirts.png',
                        is_active=True,
                        sort_order=1
                    )
                    db.session.add(cat)
                    db.session.flush()
                elif not cat.is_active:
                    cat.is_active = True
                    db.session.flush()

                prod = Product.query.filter_by(slug='signature-heavyweight-oversized-tee').first()
                if not prod:
                    prod = Product(
                        name='Signature Heavyweight Oversized Tee',
                        slug='signature-heavyweight-oversized-tee',
                        description='Engineered for the modern streetwear aesthetic. Crafted from premium 240 GSM dense combed cotton with dropped shoulders, a structured silhouette, and ribbed crew collar. Pre-shrunk for lasting shape and an authentic vintage streetwear feel.',
                        price=1299.0,
                        discount_percent=23.0,
                        stock=45,
                        category_id=cat.id,
                        is_new_arrival=True,
                        is_trending=True,
                        is_best_selling=True,
                        is_active=True,
                        sku='VS-TEE-001',
                        weight=0.35,
                        length=30.0,
                        breadth=25.0,
                        height=3.0
                    )
                    db.session.add(prod)
                    db.session.flush()

                    # Add images
                    img1 = ProductImage(
                        product_id=prod.id,
                        image_url='/static/uploads/products/demo_tshirt.png',
                        is_primary=True,
                        alt_text=prod.name,
                        sort_order=0
                    )
                    img2 = ProductImage(
                        product_id=prod.id,
                        image_url='/static/uploads/products/default_product.png',
                        is_primary=False,
                        alt_text=f'{prod.name} Alternate View',
                        sort_order=1
                    )
                    db.session.add_all([img1, img2])

                    # Add sizes
                    sizes = [
                        ProductSize(product_id=prod.id, size='S', stock=10),
                        ProductSize(product_id=prod.id, size='M', stock=15),
                        ProductSize(product_id=prod.id, size='L', stock=12),
                        ProductSize(product_id=prod.id, size='XL', stock=8),
                    ]
                    db.session.add_all(sizes)

                    # Add colors
                    colors = [
                        ProductColor(product_id=prod.id, color_name='Washed Black', color_hex='#111111'),
                        ProductColor(product_id=prod.id, color_name='Vintage Off-White', color_hex='#F5F5F3'),
                    ]
                    db.session.add_all(colors)

                db.session.commit()
            except Exception as e:
                app.logger.error(f"Error seeding default t-shirt: {e}")
                db.session.rollback()

            # Ensure all products with sizes have valid per-size stock values
            try:
                from .models import Product, ProductSize
                all_prods = Product.query.all()
                for p in all_prods:
                    p_sizes = p.sizes.all()
                    if p_sizes:
                        has_per_size_positive = any(s.stock is not None and s.stock > 0 for s in p_sizes)
                        if not has_per_size_positive and (p.stock or 0) > 0:
                            # Distribute product stock evenly across sizes
                            num_sizes = len(p_sizes)
                            base_stock = p.stock // num_sizes
                            remainder = p.stock % num_sizes
                            for idx, s in enumerate(p_sizes):
                                s.stock = base_stock + (1 if idx < remainder else 0)
                        elif has_per_size_positive:
                            # Sync total product stock to sum of size stocks
                            p.stock = sum((s.stock or 0) for s in p_sizes)
                        for s in p_sizes:
                            if s.stock is None:
                                s.stock = 0
                db.session.commit()
            except Exception as e:
                app.logger.error(f"Error auto-repairing size stocks: {e}")
                db.session.rollback()

    return app


# Provide module-level fallback so `gunicorn app:app` works seamlessly
_cached_app = None
def __getattr__(name):
    if name == 'app':
        global _cached_app
        if _cached_app is None:
            _cached_app = create_app()
        return _cached_app
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
