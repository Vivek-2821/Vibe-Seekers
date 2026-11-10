"""
User dashboard routes
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import Order, Address, Wishlist, CartItem
from app.utils import restore_product_stock
from app import db

user_bp = Blueprint('user', __name__)


def require_not_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.is_authenticated and current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated


@user_bp.route('/dashboard')
@login_required
@require_not_admin
def dashboard():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).limit(5).all()
    wishlist_count = Wishlist.query.filter_by(user_id=current_user.id).count()
    order_count = Order.query.filter_by(user_id=current_user.id).count()
    return render_template('user/dashboard.html',
                           orders=orders,
                           wishlist_count=wishlist_count,
                           order_count=order_count,
                           title='My Dashboard – Vibe Seekers')


@user_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@require_not_admin
def profile():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        
        if not name:
            flash('Name cannot be empty.', 'error')
            return redirect(url_for('user.profile'))
        
        current_user.name = name
        current_user.phone = phone
        
        # Password change
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        if new_password:
            if not current_user.check_password(current_password):
                flash('Current password is incorrect.', 'error')
                return redirect(url_for('user.profile'))
            if len(new_password) < 8:
                flash('New password must be at least 8 characters.', 'error')
                return redirect(url_for('user.profile'))
            current_user.set_password(new_password)
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('user.profile'))
    
    return render_template('user/profile.html', title='My Profile – Vibe Seekers')


@user_bp.route('/orders')
@login_required
@require_not_admin
def orders():
    all_orders = Order.query.filter_by(user_id=current_user.id)\
        .order_by(Order.created_at.desc()).all()
    return render_template('user/orders.html', orders=all_orders, title='My Orders – Vibe Seekers')


@user_bp.route('/orders/<order_number>')
@login_required
@require_not_admin
def order_detail(order_number):
    order = Order.query.filter_by(order_number=order_number, user_id=current_user.id).first_or_404()
    return render_template('user/order_detail.html', order=order,
                           title=f'Order #{order.order_number} – Vibe Seekers')


@user_bp.route('/orders/<order_number>/cancel', methods=['POST'])
@login_required
@require_not_admin
def cancel_order(order_number):
    order = Order.query.filter_by(order_number=order_number, user_id=current_user.id).first_or_404()
    
    if order.status not in ['pending', 'confirmed']:
        flash('This order cannot be cancelled as it has already been shipped.', 'error')
        return redirect(url_for('user.order_detail', order_number=order_number))
    
    order.status = 'cancelled'
    # Restore stock
    for item in order.items:
        if item.product:
            restore_product_stock(item.product, item.quantity, item.size)
    
    db.session.commit()
    flash(f'Order #{order.order_number} has been cancelled.', 'success')
    return redirect(url_for('user.orders'))


@user_bp.route('/wishlist')
@login_required
@require_not_admin
def wishlist():
    items = Wishlist.query.filter_by(user_id=current_user.id)\
        .order_by(Wishlist.added_at.desc()).all()
    return render_template('user/wishlist.html', items=items, title='My Wishlist – Vibe Seekers')


@user_bp.route('/wishlist/toggle/<int:product_id>', methods=['POST'])
@login_required
def toggle_wishlist(product_id):
    from flask import jsonify
    existing = Wishlist.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    
    if existing:
        db.session.delete(existing)
        db.session.commit()
        in_wishlist = False
        flash('Removed from wishlist.', 'info')
    else:
        w = Wishlist(user_id=current_user.id, product_id=product_id)
        db.session.add(w)
        db.session.commit()
        in_wishlist = True
        flash('Added to wishlist!', 'success')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        count = Wishlist.query.filter_by(user_id=current_user.id).count()
        return jsonify({'success': True, 'in_wishlist': in_wishlist, 'wishlist_count': count})
    
    return redirect(request.referrer or url_for('user.wishlist'))


@user_bp.route('/addresses')
@login_required
@require_not_admin
def addresses():
    user_addresses = Address.query.filter_by(user_id=current_user.id).all()
    return render_template('user/addresses.html', addresses=user_addresses,
                           title='My Addresses – Vibe Seekers')


@user_bp.route('/addresses/add', methods=['GET', 'POST'])
@login_required
@require_not_admin
def add_address():
    if request.method == 'POST':
        addr = Address(
            user_id=current_user.id,
            full_name=request.form.get('full_name', ''),
            phone=request.form.get('phone', ''),
            address_line1=request.form.get('address_line1', ''),
            address_line2=request.form.get('address_line2', ''),
            city=request.form.get('city', ''),
            state=request.form.get('state', ''),
            pincode=request.form.get('pincode', ''),
            is_default=request.form.get('is_default') == 'on'
        )
        if addr.is_default:
            Address.query.filter_by(user_id=current_user.id).update({'is_default': False})
        db.session.add(addr)
        db.session.commit()
        flash('Address added successfully!', 'success')
        return redirect(url_for('user.addresses'))
    
    return render_template('user/add_address.html', title='Add Address – Vibe Seekers')


@user_bp.route('/addresses/<int:addr_id>/delete', methods=['POST'])
@login_required
@require_not_admin
def delete_address(addr_id):
    addr = Address.query.filter_by(id=addr_id, user_id=current_user.id).first_or_404()
    db.session.delete(addr)
    db.session.commit()
    flash('Address removed.', 'info')
    return redirect(url_for('user.addresses'))
