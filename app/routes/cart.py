"""
Cart & Checkout routes with full Razorpay, COD, and coupon rules integration.
"""
import os
import re
from datetime import datetime
from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, jsonify, session, current_app)
from flask_login import login_required, current_user
from app.models import CartItem, Product, Order, OrderItem, Coupon, Address, SiteSetting
from app.utils import generate_order_number, deduct_product_stock, restore_product_stock, check_rate_limit
from app.email import send_order_confirmation_email, send_admin_new_order_email
from app.shiprocket import check_serviceability
from app import db, csrf

cart_bp = Blueprint('cart', __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_cart_items():
    """Return CartItem list for current user."""
    if current_user.is_authenticated:
        return CartItem.query.filter_by(user_id=current_user.id).all()
    return []


def calculate_cart_totals(cart_items, coupon=None, user=None):
    """
    Calculate cart financial summary:
    - Subtotal
    - Discount (validates min order, expiry, usage limit, and first order rules)
    - Shipping (Free above free_shipping_threshold, else flat_shipping_rate)
    - Total
    """
    subtotal = sum(
        (item.product.discounted_price * item.quantity)
        for item in cart_items if item.product
    )
    discount = 0.0
    coupon_code = None
    coupon_error = None

    if coupon:
        now = datetime.utcnow()
        if not coupon.is_active:
            coupon_error = "This coupon is no longer active."
        elif coupon.valid_until and coupon.valid_until < now:
            coupon_error = "This coupon has expired."
        elif coupon.max_uses > 0 and (coupon.uses or 0) >= coupon.max_uses:
            coupon_error = "This coupon has reached its maximum usage limit."
        elif coupon.min_order_amount and subtotal < coupon.min_order_amount:
            coupon_error = f"Minimum order of ₹{coupon.min_order_amount:,.0f} required for coupon {coupon.code}."
        elif getattr(coupon, 'first_order_only', False) and user:
            prev_orders = Order.query.filter_by(user_id=user.id).filter(Order.status != 'cancelled').count()
            if prev_orders > 0 or getattr(user, 'first_order_used', False):
                coupon_error = "This coupon is only valid for first-time orders."

        if not coupon_error:
            if coupon.discount_type in ('percent', 'percentage'):
                discount = round(subtotal * (coupon.discount_value / 100.0), 2)
            else:
                discount = min(round(coupon.discount_value, 2), subtotal)
            coupon_code = coupon.code

    # Automatic 10% first-order discount for new users if no manual coupon is applied
    if not coupon_code and user and not getattr(user, 'first_order_used', False):
        prev_orders = Order.query.filter_by(user_id=user.id).filter(Order.status != 'cancelled').count()
        if prev_orders == 0:
            coupon_code = 'FIRST10'
            discount = round(subtotal * 0.10, 2)

    # Configurable shipping rules from admin SiteSetting
    free_shipping_threshold = 999.0
    flat_shipping_rate = 79.0
    try:
        t_setting = SiteSetting.query.filter_by(key='free_shipping_threshold').first()
        if t_setting and t_setting.value:
            free_shipping_threshold = float(t_setting.value)
        r_setting = SiteSetting.query.filter_by(key='flat_shipping_rate').first()
        if r_setting and r_setting.value:
            flat_shipping_rate = float(r_setting.value)
    except Exception:
        pass

    shipping = 0.0 if subtotal >= free_shipping_threshold else (flat_shipping_rate if subtotal > 0 else 0.0)
    total = max(0.0, round(subtotal - discount + shipping, 2))

    return {
        'subtotal': subtotal,
        'discount': discount,
        'coupon_code': coupon_code,
        'coupon_error': coupon_error,
        'shipping': shipping,
        'free_shipping_threshold': free_shipping_threshold,
        'flat_shipping_rate': flat_shipping_rate,
        'total': total
    }


# ── Cart Views ────────────────────────────────────────────────────────────────

@cart_bp.route('/')
def view_cart():
    cart_items = get_cart_items()
    coupon = None
    coupon_code = session.get('coupon_code')
    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code, is_active=True).first()

    totals = calculate_cart_totals(cart_items, coupon,
                                   current_user if current_user.is_authenticated else None)

    return render_template('cart/cart.html',
                           cart_items=cart_items,
                           totals=totals,
                           title='Your Cart – Vibe Seekers')


@cart_bp.route('/add', methods=['POST'])
@login_required
def add_to_cart():
    product_id = request.form.get('product_id', type=int)
    quantity = request.form.get('quantity', 1, type=int)
    size = (request.form.get('size') or '').strip()
    color = (request.form.get('color') or '').strip()

    product = Product.query.get_or_404(product_id)

    if product.total_stock <= 0:
        flash('Sorry, this product is out of stock.', 'error')
        return redirect(request.referrer or url_for('shop.product_detail', slug=product.slug))

    # Check size requirement and size stock if product offers sizes
    product_sizes = product.sizes.all()
    if product_sizes:
        if not size:
            flash('Please select a size first.', 'warning')
            return redirect(request.referrer or url_for('shop.product_detail', slug=product.slug))
        size_stock = product.get_size_stock(size)
        if size_stock <= 0:
            flash(f'Sorry, size {size} is currently out of stock.', 'error')
            return redirect(request.referrer or url_for('shop.product_detail', slug=product.slug))
        max_allowed = size_stock
    else:
        max_allowed = product.total_stock

    existing = CartItem.query.filter_by(
        user_id=current_user.id, product_id=product_id, size=size, color=color
    ).first()

    if existing:
        existing.quantity = min(existing.quantity + quantity, max_allowed)
    else:
        item = CartItem(user_id=current_user.id, product_id=product_id,
                        quantity=min(quantity, max_allowed), size=size, color=color)
        db.session.add(item)

    db.session.commit()
    size_label = f" (Size {size})" if size else ""
    flash(f'<strong>{product.name}</strong>{size_label} added to cart!', 'success')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        count = CartItem.query.filter_by(user_id=current_user.id).count()
        return jsonify({'success': True, 'cart_count': count})

    return redirect(request.referrer or url_for('cart.view_cart'))


@cart_bp.route('/update', methods=['POST'])
@login_required
def update_cart():
    item_id = request.form.get('item_id', type=int)
    quantity = request.form.get('quantity', type=int)

    item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()

    if quantity <= 0:
        db.session.delete(item)
    else:
        max_allowed = item.product.get_size_stock(item.size) if (item.product and item.size) else (item.product.total_stock if item.product else 99)
        item.quantity = min(quantity, max_allowed)

    db.session.commit()
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/remove/<int:item_id>', methods=['POST'])
@login_required
def remove_from_cart(item_id):
    item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('Item removed from cart.', 'info')
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/apply-coupon', methods=['POST'])
@login_required
def apply_coupon():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    code = (request.form.get('coupon_code') or (request.get_json(silent=True) or {}).get('coupon_code') or '').strip().upper()
    
    if not code:
        msg = 'Please enter a coupon code.'
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('cart.view_cart'))

    coupon = Coupon.query.filter_by(code=code, is_active=True).first()
    now = datetime.utcnow()

    if not coupon:
        msg = 'Invalid coupon code.'
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('cart.view_cart'))

    if coupon.valid_until and coupon.valid_until < now:
        msg = 'This coupon has expired.'
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('cart.view_cart'))

    if coupon.max_uses > 0 and (coupon.uses or 0) >= coupon.max_uses:
        msg = 'This coupon has reached its maximum usage limit.'
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('cart.view_cart'))

    if getattr(coupon, 'first_order_only', False):
        prev_orders = Order.query.filter_by(user_id=current_user.id).filter(Order.status != 'cancelled').count()
        if prev_orders > 0 or getattr(current_user, 'first_order_used', False):
            msg = 'This coupon is valid only for your first order.'
            if is_ajax:
                return jsonify({'success': False, 'message': msg}), 400
            flash(msg, 'error')
            return redirect(url_for('cart.view_cart'))

    # Check cart subtotal
    cart_items = get_cart_items()
    subtotal = sum((item.product.discounted_price * item.quantity) for item in cart_items if item.product)
    if coupon.min_order_amount and subtotal < coupon.min_order_amount:
        msg = f'Minimum order amount of ₹{coupon.min_order_amount:,.0f} required for coupon {code}.'
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('cart.view_cart'))

    session['coupon_code'] = code
    msg = f'Coupon {code} applied successfully!'
    if is_ajax:
        totals = calculate_cart_totals(cart_items, coupon, current_user)
        return jsonify({'success': True, 'message': msg, 'totals': totals})
    flash(msg, 'success')
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/remove-coupon', methods=['POST'])
@login_required
def remove_coupon():
    session.pop('coupon_code', None)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    if is_ajax:
        cart_items = get_cart_items()
        totals = calculate_cart_totals(cart_items, None, current_user)
        return jsonify({'success': True, 'message': 'Coupon removed.', 'totals': totals})
    flash('Coupon removed.', 'info')
    return redirect(url_for('cart.view_cart'))


# ── Checkout & Payments ───────────────────────────────────────────────────────

@cart_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_items = get_cart_items()
    if not cart_items:
        flash('Your cart is empty.', 'info')
        return redirect(url_for('cart.view_cart'))

    coupon = None
    coupon_code = session.get('coupon_code')
    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code, is_active=True).first()

    totals = calculate_cart_totals(cart_items, coupon, current_user)
    addresses = Address.query.filter_by(user_id=current_user.id).all()
    razorpay_key_id = os.environ.get('RAZORPAY_KEY_ID', '').strip()

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or 'application/json' in request.headers.get('Accept', '')
        
        # ── Diagnostic Log: Razorpay Configuration (No secrets revealed) ──
        key_id = os.environ.get('RAZORPAY_KEY_ID', '').strip()
        key_secret = os.environ.get('RAZORPAY_KEY_SECRET', '').strip()
        key_prefix = "rzp_live_" if key_id.startswith("rzp_live_") else ("rzp_test_" if key_id.startswith("rzp_test_") else ("missing" if not key_id else "custom"))
        diag_msg = f"[RAZORPAY CONFIG] KEY_ID set: {bool(key_id)} ({key_prefix}) | KEY_SECRET set: {bool(key_secret)}"
        print(f"💳 {diag_msg}")
        current_app.logger.info(diag_msg)

        try:
            if not check_rate_limit('checkout', max_requests=25, window_seconds=300):
                msg = 'Too many requests. Please wait a moment before trying again.'
                current_app.logger.warning(f"Checkout rate limit triggered for IP: {request.remote_addr}")
                return jsonify({'success': False, 'error': msg, 'errors': [msg]}), 429

            data = request.get_json(silent=True) or request.form
            payment_method = (data.get('payment_method') or 'cod').lower()
            if payment_method not in ('cod', 'razorpay'):
                payment_method = 'razorpay'

            # ── Address resolution & validation ──────────────────────────────────
            raw_address_id = data.get('address_id')
            email = (data.get('email') or '').strip() or current_user.email
            addr = None

            if raw_address_id is not None and str(raw_address_id).strip():
                try:
                    addr_id_int = int(str(raw_address_id).strip())
                except (ValueError, TypeError):
                    return jsonify({
                        'success': False,
                        'error': 'Invalid address ID selected.',
                        'errors': ['Invalid address ID.']
                    }), 400

                addr = Address.query.filter_by(id=addr_id_int, user_id=current_user.id).first()
                if not addr:
                    return jsonify({
                        'success': False,
                        'error': 'Selected delivery address was not found.',
                        'errors': ['Selected delivery address was not found.']
                    }), 404
                if not addr.email and email:
                    addr.email = email
            else:
                full_name = (data.get('full_name') or '').strip()
                phone     = (data.get('phone') or '').strip()
                addr_l1   = (data.get('address_line1') or '').strip()
                city      = (data.get('city') or '').strip()
                state_val = (data.get('state') or '').strip()
                pincode   = (data.get('pincode') or '').strip()

                errors = []
                if not full_name or len(full_name) < 2:
                    errors.append('Full name is required.')
                if not re.match(r'^[6-9][0-9]{9}$', phone):
                    errors.append('Please enter a valid 10-digit Indian mobile number.')
                if not email or '@' not in email or '.' not in email:
                    errors.append('Please enter a valid email address for tracking.')
                if not addr_l1 or len(addr_l1) < 5:
                    errors.append('Please enter your complete street address.')
                if not city:
                    errors.append('City is required.')
                if not state_val:
                    errors.append('State is required.')
                if not re.match(r'^[1-9][0-9]{5}$', pincode):
                    errors.append('Please enter a valid 6-digit Indian PIN code.')
                else:
                    try:
                        sr_res = check_serviceability(delivery_pincode=pincode)
                        if not sr_res.get('serviceable', True):
                            errors.append(sr_res.get('message', f'PIN code {pincode} is currently not serviceable.'))
                    except Exception as sr_err:
                        current_app.logger.warning(f"Serviceability check warning: {sr_err}")

                if errors:
                    first_err = errors[0]
                    return jsonify({'success': False, 'error': first_err, 'errors': errors}), 400

                addr = Address(
                    user_id=current_user.id,
                    full_name=full_name,
                    phone=phone,
                    email=email,
                    address_line1=addr_l1,
                    address_line2=(data.get('address_line2') or '').strip(),
                    city=city,
                    state=state_val,
                    pincode=pincode,
                )
                db.session.add(addr)
                db.session.flush()

            if not addr:
                msg = 'Please select or provide a valid delivery address.'
                return jsonify({'success': False, 'error': msg, 'errors': [msg]}), 400

            # ── Pre-checkout Stock Verification ────────────────────────────────
            for item in cart_items:
                if not item.product or not item.product.is_active:
                    err_msg = f"'{item.product.name if item.product else 'An item'}' is no longer available. Please update your cart."
                    return jsonify({'success': False, 'error': err_msg, 'errors': [err_msg]}), 400

                avail = item.product.get_size_stock(item.size) if item.size else item.product.total_stock
                if avail < item.quantity:
                    sz_label = f" in size {item.size}" if item.size else ""
                    err_msg = f"Sorry, '{item.product.name}'{sz_label} only has {avail} left in stock (you requested {item.quantity})."
                    return jsonify({'success': False, 'error': err_msg, 'errors': [err_msg]}), 400

            # ── Create order record ─────────────────────────────────────────────
            order = Order(
                order_number=generate_order_number(),
                user_id=current_user.id,
                shipping_name=addr.full_name,
                shipping_phone=addr.phone,
                shipping_email=email or addr.email or current_user.email,
                shipping_address=f"{addr.address_line1}, {addr.address_line2 or ''}".strip(', '),
                shipping_city=addr.city,
                shipping_state=addr.state,
                shipping_pincode=addr.pincode,
                shipment_status='processing',
                subtotal=totals['subtotal'],
                discount_amount=totals['discount'],
                coupon_code=totals['coupon_code'],
                shipping_cost=totals['shipping'],
                total=totals['total'],
                payment_method=payment_method,
                payment_status='pending',
                status='confirmed' if payment_method == 'cod' else 'pending'
            )
            db.session.add(order)
            db.session.flush()

            # ── Order items snapshot ────────────────────────────────────────────
            for item in cart_items:
                if not item.product:
                    continue
                oi = OrderItem(
                    order_id=order.id,
                    product_id=item.product_id,
                    product_name=item.product.name,
                    product_image=item.product.primary_image,
                    price=item.product.discounted_price,
                    quantity=item.quantity,
                    size=item.size,
                    color=item.color
                )
                db.session.add(oi)

            # ── Razorpay Online Payment Flow ───────────────────────────────────
            if payment_method == 'razorpay':
                amount_paise = int(round(order.total * 100))

                if not key_id or not key_secret:
                    err_msg = 'Razorpay payment keys are not configured on the server. Please contact store support or select Cash on Delivery.'
                    current_app.logger.error(f"[CHECKOUT ERROR] {err_msg}")
                    db.session.rollback()
                    return jsonify({
                        'success': False,
                        'error': err_msg,
                        'errors': [err_msg]
                    }), 400

                try:
                    import razorpay
                    client = razorpay.Client(auth=(key_id, key_secret))
                    rzp_order = client.order.create({
                        'amount': amount_paise,
                        'currency': 'INR',
                        'receipt': order.order_number,
                        'payment_capture': 1,
                        'notes': {
                            'order_id': str(order.id),
                            'order_number': order.order_number,
                            'customer_email': order.shipping_email
                        }
                    })
                    rzp_order_id = rzp_order.get('id')
                    order.razorpay_order_id = rzp_order_id
                    print(f"💳 [RAZORPAY ORDER CREATED] ID: {rzp_order_id} | Amount: ₹{order.total}")
                except Exception as ex:
                    import traceback
                    tb = traceback.format_exc()
                    current_app.logger.error(f"❌ [RAZORPAY API EXCEPTION]: {ex}\n{tb}")
                    print(f"❌ [RAZORPAY API EXCEPTION]: {ex}\n{tb}")
                    db.session.rollback()
                    return jsonify({
                        'success': False,
                        'error': f"Payment gateway error: {str(ex)}",
                        'errors': [f"Payment gateway error: {str(ex)}"]
                    }), 400

                db.session.commit()

                return jsonify({
                    'success': True,
                    'razorpay': True,
                    'key_id': key_id,
                    'amount': amount_paise,
                    'currency': 'INR',
                    'razorpay_order_id': rzp_order_id,
                    'order_number': order.order_number,
                    'customer_name': addr.full_name,
                    'customer_email': order.shipping_email,
                    'customer_phone': addr.phone,
                    'description': f"Vibe Seekers Order #{order.order_number}"
                }), 200

            # ── Cash on Delivery (COD) Flow ────────────────────────────────────
            for item in cart_items:
                if item.product:
                    deduct_product_stock(item.product, item.quantity, item.size)
            if coupon:
                coupon.uses = (coupon.uses or 0) + 1
            if totals['coupon_code'] == 'FIRST10' and not coupon:
                current_user.first_order_used = True

            CartItem.query.filter_by(user_id=current_user.id).delete()
            session.pop('coupon_code', None)
            db.session.commit()

            # Dispatch order confirmation emails
            try:
                send_order_confirmation_email(order)
                send_admin_new_order_email(order)
            except Exception as ex:
                current_app.logger.error(f"COD order confirmation email dispatch error: {ex}")

            return jsonify({
                'success': True,
                'razorpay': False,
                'redirect': url_for('cart.order_confirmation', order_number=order.order_number)
            }), 200

        except Exception as fatal_ex:
            import traceback
            tb = traceback.format_exc()
            current_app.logger.error(f"❌ [CHECKOUT ROUTE FATAL EXCEPTION]:\n{tb}")
            print(f"❌ [CHECKOUT ROUTE FATAL EXCEPTION]: {fatal_ex}\n{tb}")
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': f"Server error: {str(fatal_ex)}",
                'errors': [f"Server error: {str(fatal_ex)}"]
            }), 500
        return redirect(url_for('cart.order_confirmation', order_number=order.order_number))

    return render_template('cart/checkout.html',
                           cart_items=cart_items,
                           totals=totals,
                           addresses=addresses,
                           razorpay_key_id=razorpay_key_id,
                           title='Checkout – Vibe Seekers')


@cart_bp.route('/payment/verify', methods=['POST'])
@login_required
def verify_payment():
    """
    Verifies Razorpay payment signature server-side.
    Activates order, deducts inventory stock, clears cart, and dispatches confirmation email.
    """
    data = request.get_json(silent=True) or request.form
    rzp_payment_id = (data.get('razorpay_payment_id') or '').strip()
    rzp_order_id = (data.get('razorpay_order_id') or '').strip()
    rzp_signature = (data.get('razorpay_signature') or '').strip()
    order_number = (data.get('order_number') or '').strip()

    if not order_number or not rzp_payment_id or not rzp_signature:
        return jsonify({'success': False, 'error': 'Incomplete payment verification payload.'}), 400

    order = Order.query.filter_by(order_number=order_number, user_id=current_user.id).first()
    if not order:
        return jsonify({'success': False, 'error': 'Order not found.'}), 404

    # Idempotent: If already processed and marked paid, return success directly
    if order.payment_status == 'paid':
        return jsonify({
            'success': True,
            'redirect': url_for('cart.order_confirmation', order_number=order.order_number)
        })

    key_id = os.environ.get('RAZORPAY_KEY_ID', '').strip()
    key_secret = os.environ.get('RAZORPAY_KEY_SECRET', '').strip()

    if not key_id or not key_secret:
        return jsonify({'success': False, 'error': 'Razorpay gateway keys are missing on the server.'}), 500

    # Signature verification
    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        client.utility.verify_payment_signature({
            'razorpay_order_id': rzp_order_id or order.razorpay_order_id,
            'razorpay_payment_id': rzp_payment_id,
            'razorpay_signature': rzp_signature
        })
        print(f"✅ [RAZORPAY SIGNATURE VERIFIED] Payment {rzp_payment_id} verified for order {order_number}")
    except Exception as ex:
        current_app.logger.error(f"Razorpay signature verification failed for #{order_number}: {ex}")
        order.payment_status = 'failed'
        db.session.commit()
        return jsonify({
            'success': False,
            'error': 'Payment verification failed. Your payment signature could not be verified.'
        }), 400

    # Payment verified! Update order status inside database transaction
    try:
        order.payment_status = 'paid'
        order.status = 'confirmed'
        order.razorpay_payment_id = rzp_payment_id
        if rzp_order_id:
            order.razorpay_order_id = rzp_order_id

        # Deduct stock per size inside transaction
        for oi in order.items:
            if oi.product:
                deduct_product_stock(oi.product, oi.quantity, oi.size)

        coupon_code = session.get('coupon_code')
        if coupon_code:
            coupon = Coupon.query.filter_by(code=coupon_code).first()
            if coupon:
                coupon.uses = (coupon.uses or 0) + 1

        CartItem.query.filter_by(user_id=current_user.id).delete()
        session.pop('coupon_code', None)
        db.session.commit()
    except Exception as ex:
        db.session.rollback()
        current_app.logger.error(f"Database error finalizing verified order #{order_number}: {ex}")
        return jsonify({'success': False, 'error': 'Database error finalizing order.'}), 500

    # Send confirmation emails
    try:
        send_order_confirmation_email(order)
        send_admin_new_order_email(order)
    except Exception as ex:
        current_app.logger.error(f"Email dispatch error for #{order_number}: {ex}")

    return jsonify({
        'success': True,
        'redirect': url_for('cart.order_confirmation', order_number=order.order_number)
    })


@cart_bp.route('/payment/webhook', methods=['POST'])
@csrf.exempt
def razorpay_webhook():
    """
    Razorpay server-to-server webhook.
    Captures async payment events: payment.captured, order.paid, payment.failed.
    Fully idempotent and cryptographically verified.
    """
    payload = request.get_data(as_text=True)
    signature = request.headers.get('X-Razorpay-Signature', '')
    webhook_secret = os.environ.get('RAZORPAY_WEBHOOK_SECRET', '').strip()

    if webhook_secret:
        if not signature:
            return jsonify({'status': 'missing signature'}), 400
        try:
            import razorpay
            client = razorpay.Client(auth=(
                os.environ.get('RAZORPAY_KEY_ID', ''),
                os.environ.get('RAZORPAY_KEY_SECRET', '')
            ))
            client.utility.verify_webhook_signature(payload, signature, webhook_secret)
        except Exception as ex:
            current_app.logger.error(f"Razorpay webhook signature verification failed: {ex}")
            return jsonify({'status': 'invalid signature'}), 400

    data = request.get_json(silent=True) or {}
    event = data.get('event')

    if event in ('payment.captured', 'order.paid'):
        entity = (data.get('payload', {}).get('payment', {}).get('entity') or
                  data.get('payload', {}).get('order', {}).get('entity') or {})
        rzp_order_id = entity.get('order_id')
        rzp_payment_id = entity.get('id')

        if rzp_order_id:
            order = Order.query.filter_by(razorpay_order_id=rzp_order_id).first()
            if order and order.payment_status != 'paid':
                try:
                    order.payment_status = 'paid'
                    order.status = 'confirmed'
                    order.razorpay_payment_id = rzp_payment_id

                    # Deduct stock per size inside transaction
                    for oi in order.items:
                        if oi.product:
                            deduct_product_stock(oi.product, oi.quantity, oi.size)

                    # Clear customer cart
                    if order.user_id:
                        CartItem.query.filter_by(user_id=order.user_id).delete()

                    db.session.commit()
                    current_app.logger.info(f"Webhook marked order #{order.order_number} as PAID.")

                    try:
                        send_order_confirmation_email(order)
                        send_admin_new_order_email(order)
                    except Exception as ex:
                        current_app.logger.error(f"Webhook email dispatch error: {ex}")
                except Exception as ex:
                    db.session.rollback()
                    current_app.logger.error(f"Webhook database error for order #{order.order_number}: {ex}")

    elif event == 'payment.failed':
        entity = data.get('payload', {}).get('payment', {}).get('entity') or {}
        rzp_order_id = entity.get('order_id')
        if rzp_order_id:
            order = Order.query.filter_by(razorpay_order_id=rzp_order_id).first()
            if order and order.payment_status != 'paid':
                order.payment_status = 'failed'
                db.session.commit()
                current_app.logger.info(f"Webhook recorded payment failed for order #{order.order_number}. Stock untouched.")

    return jsonify({'status': 'ok'}), 200


@cart_bp.route('/order-confirmation/<order_number>')
@login_required
def order_confirmation(order_number):
    order = Order.query.filter_by(order_number=order_number, user_id=current_user.id).first_or_404()
    return render_template('cart/order_confirmation.html',
                           order=order,
                           title=f'Order Confirmed! #{order.order_number} – Vibe Seekers')
