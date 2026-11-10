"""
Main public routes: homepage, static pages
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from app.models import Product, Category, Banner, SiteSetting, NewsletterSubscriber, ContactMessage, User, Review, Order
from app.email import send_welcome_newsletter_email
from app.utils import get_site_url
from app import db, csrf
from sqlalchemy import func
from datetime import datetime

main_bp = Blueprint('main', __name__)


@main_bp.route('/', methods=['GET', 'HEAD'])
def index():
    try:
        categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order).limit(8).all()
    except Exception:
        db.session.rollback()
        categories = []

    try:
        new_arrivals = Product.query.filter_by(is_new_arrival=True, is_active=True).order_by(Product.created_at.desc()).limit(8).all()
    except Exception:
        db.session.rollback()
        new_arrivals = []

    try:
        trending = Product.query.filter_by(is_trending=True, is_active=True).limit(8).all()
    except Exception:
        db.session.rollback()
        trending = []

    try:
        best_selling = Product.query.filter_by(is_best_selling=True, is_active=True).limit(8).all()
    except Exception:
        db.session.rollback()
        best_selling = []

    try:
        banners = Banner.query.filter_by(is_active=True).order_by(Banner.sort_order).all()
    except Exception:
        db.session.rollback()
        banners = []
    
    try:
        total_styles = Product.query.filter_by(is_active=True).count()
        total_customers = User.query.filter_by(is_admin=False).count()
        avg_rating_val = db.session.query(func.avg(Review.rating)).filter(Review.is_approved == True).scalar()
        stats = {
            'total_styles': total_styles,
            'total_customers': total_customers,
            'avg_rating': round(float(avg_rating_val), 1) if avg_rating_val else None
        }
    except Exception:
        db.session.rollback()
        stats = {'total_styles': 0, 'total_customers': 0, 'avg_rating': None}
    
    return render_template('index.html',
                           categories=categories,
                           new_arrivals=new_arrivals,
                           trending=trending,
                           best_selling=best_selling,
                           banners=banners,
                           stats=stats,
                           title='Vibe Seekers – Find Your Vibe')


@main_bp.route('/about')
def about():
    return render_template('pages/about.html', title='About Us – Vibe Seekers')


@main_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        
        if not all([name, email, message]):
            flash('Please fill in all required fields.', 'error')
        else:
            msg = ContactMessage(name=name, email=email, subject=subject, message=message)
            db.session.add(msg)
            db.session.commit()
            flash('Your message has been sent! We\'ll get back to you within 24 hours.', 'success')
            return redirect(url_for('main.contact'))
    
    return render_template('pages/contact.html', title='Contact Us – Vibe Seekers')


@main_bp.route('/faq')
def faq():
    return render_template('pages/faq.html', title='FAQ – Vibe Seekers')


@main_bp.route('/refund-policy')
def refund_policy():
    return render_template('pages/refund_policy.html', title='Refund Policy – Vibe Seekers')


@main_bp.route('/shipping-policy')
def shipping_policy():
    return render_template('pages/shipping_policy.html', title='Shipping Policy – Vibe Seekers')


@main_bp.route('/privacy-policy')
def privacy_policy():
    return render_template('pages/privacy_policy.html', title='Privacy Policy – Vibe Seekers')


@main_bp.route('/terms')
def terms():
    return render_template('pages/terms.html', title='Terms & Conditions – Vibe Seekers')


@main_bp.route('/webhooks/razorpay', methods=['POST'])
@csrf.exempt
def razorpay_webhook_root():
    """Root-level webhook route for Razorpay dashboard webhook integration."""
    from app.routes.cart import razorpay_webhook
    return razorpay_webhook()


@main_bp.route('/newsletter/subscribe', methods=['GET', 'POST'])
@main_bp.route('/subscribe', methods=['GET', 'POST'])
@main_bp.route('/notify-me', methods=['GET', 'POST'])
@main_bp.route('/notify', methods=['GET', 'POST'])
@main_bp.route('/api/notify-me', methods=['POST'])
@csrf.exempt
def notify_me():
    """
    Unified subscriber and product notification endpoint.
    Handles GET/POST, JSON/AJAX, and standard form submissions without 404/405 errors.
    """
    if request.method == 'GET':
        email = request.args.get('email', '').strip()
        if not email:
            return redirect(url_for('main.index') + '#newsletter')
    else:
        email = (request.form.get('email') or (request.get_json(silent=True) or {}).get('email') or '').strip().lower()

    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.is_json or
        'application/json' in request.headers.get('Accept', '')
    )

    if not email:
        msg = 'Please enter your email address.'
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(request.referrer or url_for('main.index'))

    if '@' not in email or '.' not in email.split('@')[-1] or len(email) < 5:
        msg = 'Please enter a valid email address (e.g. name@example.com).'
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(request.referrer or url_for('main.index'))

    existing = NewsletterSubscriber.query.filter_by(email=email).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.session.commit()
            msg = "Welcome back! You'll be notified on all upcoming drops."
        else:
            msg = "You're already on our notification list! We'll alert you as soon as new styles drop."
        category = 'info'
    else:
        sub = NewsletterSubscriber(email=email)
        db.session.add(sub)
        db.session.commit()
        msg = "You'll be notified! Welcome to Vibe Seekers VIP list."
        category = 'success'

        # Dispatch welcome/confirmation email in background
        try:
            send_welcome_newsletter_email(email)
        except Exception as e:
            print(f"⚠️ Notice: Welcome email dispatch error: {e}")

    if is_ajax:
        return jsonify({'success': True, 'message': msg})

    flash(msg, category)
    return redirect(request.referrer or url_for('main.index'))


@main_bp.route('/newsletter_subscribe', methods=['GET', 'POST'])
@csrf.exempt
def newsletter_subscribe_alias():
    return notify_me()


@main_bp.route('/search')
def search():
    query = request.args.get('q', '').strip()
    products = []
    if query:
        products = Product.query.filter(
            Product.is_active == True,
            Product.name.ilike(f'%{query}%')
        ).all()
    return render_template('shop/all_products.html',
                           products=products,
                           query=query,
                           title=f'Search: {query} – Vibe Seekers',
                           categories=Category.query.filter_by(is_active=True).all())


@main_bp.route('/track-order', methods=['GET', 'POST'])
@main_bp.route('/track', methods=['GET', 'POST'])
def track_order():
    order = None
    error = None
    order_number = (request.values.get('order_number') or '').strip().upper()
    contact = (request.values.get('contact') or '').strip().lower()

    if order_number:
        # Strip potential '#' symbol
        if order_number.startswith('#'):
            order_number = order_number[1:].strip()
            
        found_order = Order.query.filter_by(order_number=order_number).first()
        if not found_order:
            error = f"No order found with number #{order_number}. Please verify the order ID."
        else:
            from flask_login import current_user
            # If logged in as customer who owns it, or admin
            if current_user.is_authenticated and (found_order.user_id == current_user.id or getattr(current_user, 'is_admin', False)):
                order = found_order
            elif contact:
                # Validate contact (email or phone) for privacy
                clean_contact = contact.replace(' ', '').replace('-', '').replace('+', '')
                clean_phone = (found_order.shipping_phone or '').replace(' ', '').replace('-', '').replace('+', '')
                
                email_match = found_order.shipping_email and found_order.shipping_email.lower() == contact
                user_email_match = found_order.user and found_order.user.email.lower() == contact
                phone_match = clean_contact and clean_phone and (clean_contact in clean_phone or clean_phone in clean_contact)
                
                if email_match or user_email_match or phone_match:
                    order = found_order
                else:
                    error = "The email address or phone number entered does not match this order."
            elif current_user.is_authenticated:
                error = "This order was placed under a different account. Please enter the email or phone number used during checkout."
            else:
                error = "For security, please enter the email address or phone number you used when placing this order."

    return render_template('pages/track_order.html',
                           order=order,
                           error=error,
                           order_number=order_number,
                           contact=contact,
                           title='Track Your Order – Vibe Seekers')


# ── Health Check & SEO Endpoints ──────────────────────────────────────────────

@main_bp.route('/health')
def health():
    """Health check route for monitoring services and Render keep-alive pings."""
    db_ok = True
    try:
        db.session.execute(db.text('SELECT 1'))
    except Exception:
        db_ok = False
        db.session.rollback()

    status_code = 200 if db_ok else 503
    return jsonify({
        'status': 'healthy' if db_ok else 'degraded',
        'database': 'connected' if db_ok else 'disconnected',
        'timestamp': datetime.utcnow().isoformat()
    }), status_code


@main_bp.route('/robots.txt')
def robots_txt():
    """Generates robots.txt for search engines."""
    site_url = get_site_url()
    content = f"""User-agent: *
Allow: /
Disallow: /admin/
Disallow: /user/
Disallow: /cart/
Disallow: /auth/

Sitemap: {site_url}/sitemap.xml
"""
    return Response(content, mimetype='text/plain')


@main_bp.route('/sitemap.xml')
def sitemap_xml():
    """Generates an XML sitemap for SEO."""
    site_url = get_site_url()
    try:
        products = Product.query.filter_by(is_active=True).all()
        categories = Category.query.filter_by(is_active=True).all()
    except Exception:
        db.session.rollback()
        products, categories = [], []

    urls = [
        f"{site_url}/",
        f"{site_url}/shop",
        f"{site_url}/about",
        f"{site_url}/contact",
        f"{site_url}/faq",
        f"{site_url}/shipping-policy",
        f"{site_url}/refund-policy",
        f"{site_url}/privacy-policy",
        f"{site_url}/terms",
    ]
    for c in categories:
        urls.append(f"{site_url}/shop/category/{c.slug}")
    for p in products:
        urls.append(f"{site_url}/shop/product/{p.slug}")

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    for u in urls:
        xml_lines.append(f"  <url><loc>{u}</loc><changefreq>weekly</changefreq></url>")
    xml_lines.append('</urlset>')

    return Response("\n".join(xml_lines), mimetype='application/xml')
