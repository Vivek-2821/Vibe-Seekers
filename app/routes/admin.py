"""
Admin routes - completely separated from user side
Protected by is_admin flag
"""
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify, make_response
from flask_login import login_user, logout_user, login_required, current_user
from app.models import (User, Product, Category, Order, OrderItem, Coupon,
                        ContactMessage, NewsletterSubscriber, SiteSetting, Banner,
                        ProductImage, ProductSize, ProductColor, Review)
from app.utils import save_image, slugify, restore_product_stock
from app.email import send_order_shipped_email
from app import db
from datetime import datetime, timedelta
import json
import os

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ─── Auth ────────────────────────────────────────────────────────────────────

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email, is_admin=True).first()
        
        if user and user.check_password(password) and not user.is_blocked:
            login_user(user)
            flash('Welcome to the admin panel!', 'success')
            return redirect(url_for('admin.dashboard'))
        
        flash('Invalid admin credentials.', 'error')
    
    return render_template('admin/login.html', title='Admin Login – Vibe Seekers')


@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin.login'))


# ─── Dashboard ───────────────────────────────────────────────────────────────

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    total_orders = Order.query.count()
    total_users = User.query.filter_by(is_admin=False).count()
    total_products = Product.query.count()
    
    # Revenue (delivered + confirmed)
    from sqlalchemy import func
    revenue_result = db.session.query(func.sum(Order.total)).filter(
        Order.status.in_(['confirmed', 'shipped', 'delivered'])
    ).scalar()
    total_revenue = revenue_result or 0
    
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    low_stock = Product.query.filter(Product.stock <= 5, Product.is_active == True).all()
    unread_messages = ContactMessage.query.filter_by(is_read=False).count()
    
    # Chart data: orders per day last 7 days
    chart_data = []
    for i in range(6, -1, -1):
        day = datetime.utcnow() - timedelta(days=i)
        count = Order.query.filter(
            db.func.date(Order.created_at) == day.date()
        ).count()
        chart_data.append({'date': day.strftime('%b %d'), 'count': count})
    
    return render_template('admin/dashboard.html',
                           total_orders=total_orders,
                           total_users=total_users,
                           total_products=total_products,
                           total_revenue=total_revenue,
                           recent_orders=recent_orders,
                           low_stock=low_stock,
                           unread_messages=unread_messages,
                           chart_data=json.dumps(chart_data),
                           title='Admin Dashboard – Vibe Seekers')


# ─── Products ────────────────────────────────────────────────────────────────

@admin_bp.route('/products')
@login_required
@admin_required
def products():
    page = request.args.get('page', 1, type=int)
    products = Product.query.order_by(Product.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('admin/products.html', products=products, title='Products – Admin')


@admin_bp.route('/products/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_product():
    categories = Category.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        slug_base = slugify(name)
        slug = slug_base
        counter = 1
        while Product.query.filter_by(slug=slug).first():
            slug = f'{slug_base}-{counter}'
            counter += 1
        
        product = Product(
            name=name,
            slug=slug,
            description=request.form.get('description', ''),
            price=float(request.form.get('price', 0)),
            discount_percent=float(request.form.get('discount_percent', 0)),
            stock=int(request.form.get('stock', 0)),
            category_id=request.form.get('category_id') or None,
            is_new_arrival=request.form.get('is_new_arrival') == 'on',
            is_trending=request.form.get('is_trending') == 'on',
            is_best_selling=request.form.get('is_best_selling') == 'on',
            is_active=request.form.get('is_active') == 'on',
            sku=request.form.get('sku', ''),
            weight=float(request.form.get('weight', 0.5) or 0.5),
            length=float(request.form.get('length', 30.0) or 30.0),
            breadth=float(request.form.get('breadth', 20.0) or 20.0),
            height=float(request.form.get('height', 5.0) or 5.0),
            meta_title=request.form.get('meta_title', ''),
            meta_description=request.form.get('meta_description', '')
        )
        db.session.add(product)
        db.session.flush()
        
        # Images
        files = request.files.getlist('images')
        for i, f in enumerate(files):
            if f and f.filename:
                url = save_image(f, 'products')
                if url:
                    img = ProductImage(product_id=product.id, image_url=url,
                                       is_primary=(i == 0), sort_order=i)
                    db.session.add(img)
        
        # Save sizes, per-size stock, and colors
        _save_product_sizes_and_colors(product)
        
        db.session.commit()
        flash(f'Product "{product.name}" added successfully!', 'success')
        return redirect(url_for('admin.products'))
    
    return render_template('admin/product_form.html', product=None, categories=categories,
                           title='Add Product – Admin')


def _save_product_sizes_and_colors(product):
    """
    Saves or updates sizes, per-size stock levels, and colors.
    Calculates total product stock from size stocks if per-size stocks are provided.
    """
    size_names = request.form.getlist('size_name[]')
    size_stocks = request.form.getlist('size_stock[]')
    sizes_str = request.form.get('sizes', '').strip()

    # Clear existing sizes
    ProductSize.query.filter_by(product_id=product.id).delete()

    total_size_stock = 0
    has_valid_sizes = False

    if size_names:
        for s_name, s_stk in zip(size_names, size_stocks):
            s_name = s_name.strip().upper()
            if s_name:
                has_valid_sizes = True
                try:
                    s_int = max(0, int(s_stk))
                except (ValueError, TypeError):
                    s_int = 0
                total_size_stock += s_int
                db.session.add(ProductSize(product_id=product.id, size=s_name, stock=s_int))
    elif sizes_str:
        s_list = [s.strip().upper() for s in sizes_str.split(',') if s.strip()]
        if s_list:
            has_valid_sizes = True
            current_total = int(product.stock or 0)
            per_size = max(1, current_total // len(s_list)) if current_total > 0 else 0
            for s_name in s_list:
                total_size_stock += per_size
                db.session.add(ProductSize(product_id=product.id, size=s_name, stock=per_size))

    # Keep total product stock consistent
    if has_valid_sizes and total_size_stock > 0:
        product.stock = total_size_stock

    # Colors
    color_names = request.form.getlist('color_name[]')
    color_hexes = request.form.getlist('color_hex[]')
    ProductColor.query.filter_by(product_id=product.id).delete()
    for cn, ch in zip(color_names, color_hexes):
        cn_clean = cn.strip()
        if cn_clean:
            db.session.add(ProductColor(product_id=product.id, color_name=cn_clean, color_hex=ch.strip() or '#000000'))


@admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    categories = Category.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        product.name = request.form.get('name', product.name).strip()
        product.description = request.form.get('description', '')
        product.price = float(request.form.get('price', 0))
        product.discount_percent = float(request.form.get('discount_percent', 0))
        product.stock = int(request.form.get('stock', 0))
        product.category_id = request.form.get('category_id') or None
        product.is_new_arrival = request.form.get('is_new_arrival') == 'on'
        product.is_trending = request.form.get('is_trending') == 'on'
        product.is_best_selling = request.form.get('is_best_selling') == 'on'
        product.is_active = request.form.get('is_active') == 'on'
        product.sku = request.form.get('sku', '')
        product.weight = float(request.form.get('weight', 0.5) or 0.5)
        product.length = float(request.form.get('length', 30.0) or 30.0)
        product.breadth = float(request.form.get('breadth', 20.0) or 20.0)
        product.height = float(request.form.get('height', 5.0) or 5.0)
        product.meta_title = request.form.get('meta_title', '')
        product.meta_description = request.form.get('meta_description', '')
        product.updated_at = datetime.utcnow()
        
        # New images
        files = request.files.getlist('images')
        existing_count = product.images.count()
        for i, f in enumerate(files):
            if f and f.filename:
                url = save_image(f, 'products')
                if url:
                    img = ProductImage(product_id=product.id, image_url=url,
                                       is_primary=(existing_count == 0 and i == 0),
                                       sort_order=existing_count + i)
                    db.session.add(img)

        # Save sizes, per-size stock, and colors
        _save_product_sizes_and_colors(product)
        
        db.session.commit()
        flash(f'Product "{product.name}" updated!', 'success')
        return redirect(url_for('admin.products'))
    
    return render_template('admin/product_form.html', product=product, categories=categories,
                           title=f'Edit {product.name} – Admin')


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    name = product.name
    try:
        # Unlink order items so order history remains intact without FK error
        for item in product.order_items.all():
            item.product_id = None
        db.session.delete(product)
        db.session.commit()
        flash(f'Product "{name}" has been permanently deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        product.is_active = False
        db.session.commit()
        flash(f'Product "{name}" has been removed from customer storefront.', 'warning')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/image/<int:image_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_product_image(image_id):
    img = ProductImage.query.get_or_404(image_id)
    db.session.delete(img)
    db.session.commit()
    return jsonify({'success': True})


# ─── Categories ──────────────────────────────────────────────────────────────

@admin_bp.route('/categories')
@login_required
@admin_required
def categories():
    cats = Category.query.order_by(Category.sort_order).all()
    return render_template('admin/categories.html', categories=cats, title='Categories – Admin')


@admin_bp.route('/categories/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_category():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        slug = slugify(name)
        counter = 1
        base_slug = slug
        while Category.query.filter_by(slug=slug).first():
            slug = f'{base_slug}-{counter}'
            counter += 1
        
        image_url = None
        if 'image' in request.files:
            image_url = save_image(request.files['image'], 'categories', (600, 600))
        
        cat = Category(
            name=name, slug=slug,
            description=request.form.get('description', ''),
            image=image_url,
            is_active=request.form.get('is_active') == 'on',
            sort_order=int(request.form.get('sort_order', 0))
        )
        db.session.add(cat)
        db.session.commit()
        flash(f'Category "{cat.name}" added!', 'success')
        return redirect(url_for('admin.categories'))
    
    return render_template('admin/category_form.html', category=None, title='Add Category – Admin')


@admin_bp.route('/categories/<int:cat_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    
    if request.method == 'POST':
        cat.name = request.form.get('name', cat.name).strip()
        cat.description = request.form.get('description', '')
        cat.is_active = request.form.get('is_active') == 'on'
        cat.sort_order = int(request.form.get('sort_order', 0))
        
        if 'image' in request.files and request.files['image'].filename:
            url = save_image(request.files['image'], 'categories', (600, 600))
            if url:
                cat.image = url
        
        db.session.commit()
        flash(f'Category "{cat.name}" updated!', 'success')
        return redirect(url_for('admin.categories'))
    
    return render_template('admin/category_form.html', category=cat,
                           title=f'Edit {cat.name} – Admin')


@admin_bp.route('/categories/<int:cat_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    name = cat.name
    try:
        # Unlink any products assigned to this category
        for p in cat.products.all():
            p.category_id = None
        db.session.delete(cat)
        db.session.commit()
        flash(f'Category "{name}" has been permanently deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        cat.is_active = False
        db.session.commit()
        flash(f'Category "{name}" deactivated.', 'warning')
    return redirect(url_for('admin.categories'))


# ─── Orders ──────────────────────────────────────────────────────────────────

@admin_bp.route('/orders')
@login_required
@admin_required
def orders():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status')
    query = Order.query.order_by(Order.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    orders = query.paginate(page=page, per_page=20)
    return render_template('admin/orders.html', orders=orders,
                           status_filter=status_filter, title='Orders – Admin')


@admin_bp.route('/orders/<int:order_id>')
@login_required
@admin_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('admin/order_detail.html', order=order,
                           title=f'Order #{order.order_number} – Admin')


@admin_bp.route('/orders/<int:order_id>/update-status', methods=['POST'])
@login_required
@admin_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    old_status = (order.status or '').lower()
    new_status = (request.form.get('status') or '').strip().lower()
    tracking = request.form.get('tracking_number', '').strip()
    courier = request.form.get('courier_name', '').strip()

    valid_statuses = ['pending', 'paid', 'confirmed', 'packed', 'shipped', 'delivered', 'cancelled', 'refunded']
    if new_status in valid_statuses:
        if new_status == 'paid':
            order.payment_status = 'paid'
            order.status = 'confirmed'
        else:
            order.status = new_status

        if tracking:
            order.tracking_number = tracking
        if courier:
            order.courier_name = courier

        if new_status == 'delivered':
            order.payment_status = 'paid'

        # If transitioning to shipped, send tracking notification to customer
        if new_status == 'shipped' and old_status != 'shipped':
            try:
                send_order_shipped_email(order)
            except Exception as mail_err:
                print(f"⚠️ [ADMIN] Shipping notification email failed: {mail_err}")

        # If cancelling or refunding, restore inventory stock if it was deducted
        if new_status in ['cancelled', 'refunded'] and old_status not in ['cancelled', 'refunded']:
            for oi in order.items:
                if oi.product:
                    restore_product_stock(oi.product, oi.quantity, oi.size)

        db.session.commit()
        flash(f'Order #{order.order_number} status updated to {new_status.upper()}.', 'success')
    else:
        flash(f'Invalid status: {new_status}', 'error')

    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/mark-paid', methods=['POST'])
@login_required
@admin_required
def mark_order_paid(order_id):
    """Mark an order as paid manually."""
    order = Order.query.get_or_404(order_id)
    order.payment_status = 'paid'
    order.status = 'confirmed'
    db.session.commit()
    flash(f'Order #{order.order_number} marked as PAID and confirmed.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/refund', methods=['POST'])
@login_required
@admin_required
def refund_order(order_id):
    """Initiates a refund via Razorpay API and marks order as refunded."""
    order = Order.query.get_or_404(order_id)
    if not order.razorpay_payment_id:
        flash('This order does not have a Razorpay payment ID to refund.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order_id))

    key_id = os.environ.get('RAZORPAY_KEY_ID', '').strip()
    key_secret = os.environ.get('RAZORPAY_KEY_SECRET', '').strip()

    if not key_id or not key_secret:
        flash('Razorpay API keys are not configured in environment variables.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order_id))

    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        amount_paise = int(round(order.total * 100))
        refund_res = client.payment.refund(order.razorpay_payment_id, {
            'amount': amount_paise,
            'notes': {
                'order_number': order.order_number,
                'reason': 'Refund initiated by store admin'
            }
        })
        print(f"💳 [RAZORPAY REFUND SUCCESS] Refund ID: {refund_res.get('id')} for Order #{order.order_number}")
        order.payment_status = 'refunded'
        order.status = 'refunded'

        # Restore inventory stock
        for oi in order.items:
            if oi.product:
                restore_product_stock(oi.product, oi.quantity, oi.size)

        db.session.commit()
        flash(f'Successfully refunded ₹{order.total:,.0f} via Razorpay (Refund ID: {refund_res.get("id")}). Inventory restored.', 'success')
    except Exception as ex:
        print(f"❌ [RAZORPAY REFUND ERROR]: {ex}")
        flash(f'Razorpay refund failed: {str(ex)}', 'error')

    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/ship', methods=['POST'])
@login_required
@admin_required
def ship_order(order_id):
    """
    Creates shipment through Shiprocket API and saves AWB number,
    courier name, and tracking link.
    """
    from app.shiprocket import create_shiprocket_order
    order = Order.query.get_or_404(order_id)

    if order.status == 'cancelled':
        flash('Cannot ship a cancelled order.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order_id))

    if order.awb_code:
        flash(f'Order #{order.order_number} is already shipped with AWB #{order.awb_code}.', 'info')
        return redirect(url_for('admin.order_detail', order_id=order_id))

    success, res = create_shiprocket_order(order)
    if success:
        awb = res.get('awb_code', '')
        courier = res.get('courier_name', 'Shiprocket Partner')
        demo_note = " (Demo Mode)" if res.get('is_demo') else ""
        flash(f'🚀 Order #{order.order_number} shipped via {courier}! AWB: {awb}{demo_note}', 'success')
    else:
        err_msg = res.get('message', 'Failed to create shipment.')
        flash(f'Shiprocket error: {err_msg}', 'error')

    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/sync-tracking', methods=['POST'])
@login_required
@admin_required
def sync_order_tracking(order_id):
    """
    Refresh tracking status from Shiprocket API for an individual order.
    """
    from app.shiprocket import sync_order_status
    order = Order.query.get_or_404(order_id)
    if not order.awb_code:
        flash('No AWB code found to track.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order_id))

    success, status = sync_order_status(order)
    if success:
        flash(f'Tracking synced! Current shipment status: {status.upper()}', 'success')
    else:
        flash(f'Could not sync tracking: {status}', 'error')

    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/cancel-shipment', methods=['POST'])
@login_required
@admin_required
def cancel_shipment(order_id):
    """
    Cancel shipment in Shiprocket for an order that is shipped but not yet delivered.
    """
    from app.shiprocket import cancel_shiprocket_shipment
    order = Order.query.get_or_404(order_id)

    success, msg = cancel_shiprocket_shipment(order)
    if success:
        flash(f'✅ {msg}', 'success')
    else:
        flash(f'❌ Could not cancel shipment: {msg}', 'error')

    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/sync-all-tracking', methods=['POST'])
@login_required
@admin_required
def sync_all_orders_tracking():
    """Sync all active shipments with Shiprocket."""
    from app.shiprocket import sync_order_status
    active_orders = Order.query.filter(
        Order.awb_code.isnot(None),
        Order.shipment_status.in_(['processing', 'shipped', 'out for delivery'])
    ).all()
    count = 0
    for o in active_orders:
        ok, _ = sync_order_status(o)
        if ok:
            count += 1
    flash(f'Synced {count} active shipment(s) with Shiprocket.', 'info')
    return redirect(url_for('admin.orders'))


# ─── Users ───────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    page = request.args.get('page', 1, type=int)
    users = User.query.filter_by(is_admin=False).order_by(User.created_at.desc())\
        .paginate(page=page, per_page=20)
    return render_template('admin/users.html', users=users, title='Users – Admin')


@admin_bp.route('/users/<int:user_id>/toggle-block', methods=['POST'])
@login_required
@admin_required
def toggle_user_block(user_id):
    user = User.query.get_or_404(user_id)
    user.is_blocked = not user.is_blocked
    db.session.commit()
    status = 'blocked' if user.is_blocked else 'unblocked'
    flash(f'User {user.email} has been {status}.', 'success')
    return redirect(url_for('admin.users'))


# ─── Coupons ─────────────────────────────────────────────────────────────────

@admin_bp.route('/coupons')
@login_required
@admin_required
def coupons():
    coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
    return render_template('admin/coupons.html', coupons=coupons, title='Coupons – Admin')


@admin_bp.route('/coupons/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_coupon():
    if request.method == 'POST':
        valid_until_str = request.form.get('valid_until', '')
        valid_until = datetime.strptime(valid_until_str, '%Y-%m-%d') if valid_until_str else None
        
        coupon = Coupon(
            code=request.form.get('code', '').strip().upper(),
            discount_type=request.form.get('discount_type', 'percent'),
            discount_value=float(request.form.get('discount_value', 0)),
            min_order_amount=float(request.form.get('min_order_amount', 0)),
            max_uses=int(request.form.get('max_uses', 0)),
            is_active=request.form.get('is_active') == 'on',
            valid_until=valid_until,
            description=request.form.get('description', '')
        )
        db.session.add(coupon)
        db.session.commit()
        flash(f'Coupon "{coupon.code}" created!', 'success')
        return redirect(url_for('admin.coupons'))
    
    return render_template('admin/coupon_form.html', coupon=None, title='Add Coupon – Admin')


@admin_bp.route('/coupons/<int:coupon_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    db.session.delete(coupon)
    db.session.commit()
    flash(f'Coupon "{coupon.code}" deleted.', 'success')
    return redirect(url_for('admin.coupons'))


# ─── Messages & Newsletter ────────────────────────────────────────────────────

@admin_bp.route('/messages')
@login_required
@admin_required
def messages():
    msgs = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    # Mark all as read
    ContactMessage.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('admin/messages.html', messages=msgs, title='Messages – Admin')


@admin_bp.route('/newsletter')
@login_required
@admin_required
def newsletter():
    subs = NewsletterSubscriber.query.order_by(NewsletterSubscriber.subscribed_at.desc()).all()
    return render_template('admin/newsletter.html', subscribers=subs, title='Newsletter – Admin')


# ─── Site Settings ───────────────────────────────────────────────────────────

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    if request.method == 'POST':
        keys = ['announcement_text', 'announcement_active', 'store_name', 'store_email',
                'store_phone', 'store_address', 'social_instagram', 'social_facebook',
                'social_twitter', 'social_youtube', 'upi_id', 'razorpay_key_id',
                'shiprocket_pickup_pincode', 'shiprocket_pickup_location',
                'free_shipping_threshold', 'flat_shipping_rate']
        
        for key in keys:
            value = request.form.get(key, '')
            setting = SiteSetting.query.filter_by(key=key).first()
            if setting:
                setting.value = value
            else:
                db.session.add(SiteSetting(key=key, value=value))
        
        db.session.commit()
        flash('Settings saved!', 'success')
        return redirect(url_for('admin.settings'))
    
    settings_dict = {s.key: s.value for s in SiteSetting.query.all()}
    return render_template('admin/settings.html', settings=settings_dict, title='Settings – Admin')


# ─── Banners ─────────────────────────────────────────────────────────────────

@admin_bp.route('/banners')
@login_required
@admin_required
def banners():
    banners = Banner.query.order_by(Banner.sort_order).all()
    return render_template('admin/banners.html', banners=banners, title='Banners – Admin')


@admin_bp.route('/banners/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_banner():
    if request.method == 'POST':
        image_url = None
        if 'image' in request.files and request.files['image'].filename:
            image_url = save_image(request.files['image'], 'banners', (1920, 800))
        image_url_mobile = None
        if 'image_mobile' in request.files and request.files['image_mobile'].filename:
            image_url_mobile = save_image(request.files['image_mobile'], 'banners', (1080, 1350))
        
        banner = Banner(
            title=request.form.get('title', ''),
            subtitle=request.form.get('subtitle', ''),
            cta_text=request.form.get('cta_text', ''),
            cta_url=request.form.get('cta_url', ''),
            image_url=image_url,
            image_url_mobile=image_url_mobile,
            is_active=request.form.get('is_active') == 'on',
            sort_order=int(request.form.get('sort_order', 0))
        )
        db.session.add(banner)
        db.session.commit()
        flash('Banner added!', 'success')
        return redirect(url_for('admin.banners'))
    
    return render_template('admin/banner_form.html', banner=None, title='Add Banner – Admin')


@admin_bp.route('/banners/<int:banner_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_banner(banner_id):
    banner = Banner.query.get_or_404(banner_id)
    if request.method == 'POST':
        if 'image' in request.files and request.files['image'].filename:
            banner.image_url = save_image(request.files['image'], 'banners', (1920, 800))
        if 'image_mobile' in request.files and request.files['image_mobile'].filename:
            banner.image_url_mobile = save_image(request.files['image_mobile'], 'banners', (1080, 1350))
        banner.title = request.form.get('title', '').strip()
        banner.subtitle = request.form.get('subtitle', '').strip()
        banner.cta_text = request.form.get('cta_text', '').strip()
        banner.cta_url = request.form.get('cta_url', '').strip()
        banner.is_active = request.form.get('is_active') == 'on'
        banner.sort_order = int(request.form.get('sort_order', 0) or 0)
        db.session.commit()
        flash('Banner updated successfully!', 'success')
        return redirect(url_for('admin.banners'))
    
    return render_template('admin/banner_form.html', banner=banner, title='Edit Banner – Admin')


@admin_bp.route('/banners/<int:banner_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_banner(banner_id):
    banner = Banner.query.get_or_404(banner_id)
    db.session.delete(banner)
    db.session.commit()
    flash('Banner deleted.', 'success')
    return redirect(url_for('admin.banners'))


# ─── Reviews ─────────────────────────────────────────────────────────────────

@admin_bp.route('/reviews')
@login_required
@admin_required
def reviews():
    all_reviews = Review.query.order_by(Review.created_at.desc()).all()
    return render_template('admin/reviews.html', reviews=all_reviews, title='Reviews – Admin')


@admin_bp.route('/reviews/<int:review_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_review(review_id):
    review = Review.query.get_or_404(review_id)
    review.is_approved = not review.is_approved
    db.session.commit()
    return redirect(url_for('admin.reviews'))


# ─── Demo Data Seeder ─────────────────────────────────────────────────────────

# Mapping: product slug → demo image filename in static/uploads/products/
DEMO_PRODUCT_IMAGES = {
    'classic-oversized-tee':   '/static/uploads/products/demo_tshirt.png',
    'acid-wash-graphic-tee':   '/static/uploads/products/demo_tshirt.png',
    'tie-dye-oversized-tee':   '/static/uploads/products/demo_tshirt.png',
    'streetwear-pullover-hoodie': '/static/uploads/products/demo_hoodie.png',
    'zip-up-hoodie':           '/static/uploads/products/demo_hoodie.png',
    'cargo-jogger-pants':      '/static/uploads/products/demo_jogger.png',
    'slim-fit-track-pants':    '/static/uploads/products/demo_jogger.png',
    'bomber-jacket':           '/static/uploads/products/demo_jacket.png',
}

DEMO_BANNER_DATA = [
    {
        'title': 'Define Your Vibe',
        'subtitle': 'New Season Drop',
        'cta_text': 'Shop Now',
        'cta_url': '/shop',
        'image_url': '/static/uploads/banners/hero_banner.png',
        'sort_order': 0,
    },
    {
        'title': 'Street Style Essentials',
        'subtitle': 'Trending Now',
        'cta_text': 'Explore Trending',
        'cta_url': '/trending',
        'image_url': '/static/uploads/banners/hero_banner.png',
        'sort_order': 1,
    },
]


@admin_bp.route('/seed-demo-data', methods=['POST'])
@login_required
@admin_required
def seed_demo_data():
    """
    Seeds the database with sample categories, products (with images) and banners.
    Only adds if fewer than 3 categories exist.
    """
    import os
    try:
        if Category.query.count() < 3:
            cats_data = [
                ('T-Shirts', 't-shirts', 'Casual and premium tees'),
                ('Hoodies', 'hoodies', 'Cozy hoodies and sweatshirts'),
                ('Joggers', 'joggers', 'Comfortable joggers and track pants'),
            ]
            cats = {}
            for name, slug, desc in cats_data:
                existing = Category.query.filter_by(slug=slug).first()
                if not existing:
                    c = Category(name=name, slug=slug, description=desc, is_active=True,
                                sort_order=len(cats))
                    db.session.add(c)
                    db.session.flush()
                    cats[slug] = c
                else:
                    cats[slug] = existing
            db.session.commit()

        # Re-fetch cats
        all_cats = {c.slug: c for c in Category.query.all()}

        if Product.query.count() < 5:
            products_data = [
                {
                    'name': 'Classic Oversized Tee',
                    'slug': 'classic-oversized-tee',
                    'description': 'Premium 100% cotton oversized tee with a relaxed silhouette perfect for everyday wear. Drop shoulder cut, ribbed collar, pre-washed for a vintage feel.',
                    'price': 799,
                    'discount_percent': 15,
                    'stock': 50,
                    'category': 't-shirts',
                    'sku': 'VS-TEE-001',
                    'is_new_arrival': True,
                    'is_trending': True,
                    'sizes': ['XS', 'S', 'M', 'L', 'XL', 'XXL'],
                    'colors': [('Black', '#000000'), ('White', '#ffffff'), ('Olive', '#6b7c4a')],
                },
                {
                    'name': 'Acid Wash Graphic Tee',
                    'slug': 'acid-wash-graphic-tee',
                    'description': 'Retro-inspired acid wash tee with hand-drawn graphic print. Made from heavyweight cotton for a premium feel.',
                    'price': 999,
                    'discount_percent': 0,
                    'stock': 30,
                    'category': 't-shirts',
                    'sku': 'VS-TEE-002',
                    'is_new_arrival': True,
                    'is_trending': False,
                    'sizes': ['S', 'M', 'L', 'XL'],
                    'colors': [('Washed Blue', '#7ba7d4'), ('Washed Black', '#3a3a3a')],
                },
                {
                    'name': 'Streetwear Pullover Hoodie',
                    'slug': 'streetwear-pullover-hoodie',
                    'description': 'Ultra-soft 400gsm fleece hoodie with kangaroo pocket and adjustable drawstrings. The perfect layering piece for cooler days.',
                    'price': 1999,
                    'discount_percent': 20,
                    'stock': 25,
                    'category': 'hoodies',
                    'sku': 'VS-HOOD-001',
                    'is_new_arrival': False,
                    'is_trending': True,
                    'is_best_selling': True,
                    'sizes': ['S', 'M', 'L', 'XL', 'XXL'],
                    'colors': [('Charcoal', '#36454F'), ('Deep Navy', '#17223B'), ('Cream', '#f5f0e8')],
                },
                {
                    'name': 'Cargo Jogger Pants',
                    'slug': 'cargo-jogger-pants',
                    'description': 'Relaxed-fit cargo joggers with multiple utility pockets. Elastic waistband with drawstring for the perfect fit.',
                    'price': 1599,
                    'discount_percent': 10,
                    'stock': 40,
                    'category': 'joggers',
                    'sku': 'VS-JOG-001',
                    'is_new_arrival': True,
                    'is_trending': True,
                    'sizes': ['S', 'M', 'L', 'XL'],
                    'colors': [('Black', '#000000'), ('Khaki', '#c3b091'), ('Army Green', '#4a5940')],
                },

                {
                    'name': 'Tie-Dye Oversized Tee',
                    'slug': 'tie-dye-oversized-tee',
                    'description': 'Hand-crafted tie-dye tee for a unique, one-of-a-kind look. No two pieces are identical.',
                    'price': 899,
                    'discount_percent': 0,
                    'stock': 20,
                    'category': 't-shirts',
                    'sku': 'VS-TEE-003',
                    'is_new_arrival': False,
                    'is_trending': True,
                    'is_best_selling': True,
                    'sizes': ['S', 'M', 'L', 'XL'],
                    'colors': [('Purple Haze', '#9b59b6'), ('Ocean Blue', '#2980b9')],
                },
                {
                    'name': 'Zip-Up Hoodie',
                    'slug': 'zip-up-hoodie',
                    'description': 'Classic zip-up hoodie made from premium fleece. Features two side pockets and a full-length zip. A wardrobe staple.',
                    'price': 1799,
                    'discount_percent': 0,
                    'stock': 35,
                    'category': 'hoodies',
                    'sku': 'VS-HOOD-002',
                    'is_new_arrival': False,
                    'is_trending': False,
                    'is_best_selling': True,
                    'sizes': ['XS', 'S', 'M', 'L', 'XL', 'XXL'],
                    'colors': [('Black', '#000000'), ('Light Grey', '#d0d0d0'), ('Navy', '#1f3a5f')],
                },
                {
                    'name': 'Slim Fit Track Pants',
                    'slug': 'slim-fit-track-pants',
                    'description': 'Modern slim-fit track pants with a subtle side stripe. Made from moisture-wicking fabric for sport and casual wear.',
                    'price': 1299,
                    'discount_percent': 0,
                    'stock': 45,
                    'category': 'joggers',
                    'sku': 'VS-JOG-002',
                    'is_new_arrival': True,
                    'is_trending': False,
                    'sizes': ['S', 'M', 'L', 'XL', 'XXL'],
                    'colors': [('Black', '#000000'), ('Maroon', '#800020')],
                },
            ]

            for pd in products_data:
                if Product.query.filter_by(slug=pd['slug']).first():
                    continue
                cat_obj = all_cats.get(pd['category'])
                p = Product(
                    name=pd['name'],
                    slug=pd['slug'],
                    description=pd['description'],
                    price=pd['price'],
                    discount_percent=pd.get('discount_percent', 0),
                    stock=pd['stock'],
                    category_id=cat_obj.id if cat_obj else None,
                    sku=pd['sku'],
                    is_new_arrival=pd.get('is_new_arrival', False),
                    is_trending=pd.get('is_trending', False),
                    is_best_selling=pd.get('is_best_selling', False),
                    is_active=True,
                )
                db.session.add(p)
                db.session.flush()

                # Attach demo image if available
                demo_img_url = DEMO_PRODUCT_IMAGES.get(pd['slug'])
                if demo_img_url:
                    db.session.add(ProductImage(
                        product_id=p.id,
                        image_url=demo_img_url,
                        is_primary=True,
                        alt_text=pd['name'],
                        sort_order=0
                    ))

                # Sizes
                for size in pd.get('sizes', []):
                    db.session.add(ProductSize(product_id=p.id, size=size, stock=p.stock // len(pd['sizes'])))

                # Colors
                for cn, ch in pd.get('colors', []):
                    db.session.add(ProductColor(product_id=p.id, color_name=cn, color_hex=ch))

            db.session.commit()
            flash('🎉 Demo data seeded! Products with images have been added to the store.', 'success')
        else:
            flash('ℹ️ Products already exist. Skipping product seed.', 'info')

        # Seed demo banners
        if Banner.query.count() == 0:
            for bd in DEMO_BANNER_DATA:
                db.session.add(Banner(
                    title=bd['title'],
                    subtitle=bd['subtitle'],
                    cta_text=bd['cta_text'],
                    cta_url=bd['cta_url'],
                    image_url=bd['image_url'],
                    is_active=True,
                    sort_order=bd['sort_order']
                ))
            db.session.commit()
            flash('🖼️ Demo banners added to the hero slider.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error seeding data: {str(e)}', 'error')

    return redirect(url_for('admin.demo_images'))


# ─── Demo Images Manager ──────────────────────────────────────────────────────

@admin_bp.route('/demo-images')
@login_required
@admin_required
def demo_images():
    """View all demo/seeded images – banners and product images – with delete options."""
    product_images = (
        db.session.query(ProductImage, Product)
        .join(Product, ProductImage.product_id == Product.id)
        .order_by(ProductImage.id.desc())
        .all()
    )
    banners = Banner.query.order_by(Banner.sort_order).all()
    return render_template('admin/demo_images.html',
                           product_images=product_images,
                           banners=banners,
                           title='Demo Images – Admin')


@admin_bp.route('/demo-images/product-image/<int:image_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_demo_product_image(image_id):
    img = ProductImage.query.get_or_404(image_id)
    db.session.delete(img)
    db.session.commit()
    flash('Product image removed.', 'success')
    return redirect(url_for('admin.demo_images'))


@admin_bp.route('/demo-images/banner/<int:banner_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_demo_banner(banner_id):
    banner = Banner.query.get_or_404(banner_id)
    db.session.delete(banner)
    db.session.commit()
    flash('Banner removed.', 'success')
    return redirect(url_for('admin.demo_images'))


@admin_bp.route('/demo-images/clear-all', methods=['POST'])
@login_required
@admin_required
def clear_all_demo_images():
    """Remove all product images and banners at once."""
    try:
        ProductImage.query.delete()
        Banner.query.delete()
        db.session.commit()
        flash('✅ All demo images and banners have been cleared.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('admin.demo_images'))


@admin_bp.route('/chart-data')
@login_required
@admin_required
def chart_data():
    """Returns order counts + revenue for last 7 days as JSON for dashboard charts."""
    from sqlalchemy import func
    data = []
    for i in range(6, -1, -1):
        day = datetime.utcnow() - timedelta(days=i)
        count = Order.query.filter(
            db.func.date(Order.created_at) == day.date()
        ).count()
        rev_result = db.session.query(func.sum(Order.total)).filter(
            db.func.date(Order.created_at) == day.date(),
            Order.status.in_(['confirmed', 'shipped', 'delivered'])
        ).scalar()
        data.append({
            'date': day.strftime('%b %d'),
            'orders': count,
            'revenue': float(rev_result or 0)
        })
    return jsonify(data)
