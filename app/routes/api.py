"""API / AJAX endpoints"""
import logging
from flask import Blueprint, jsonify, request
from flask_login import current_user
from app.models import Product, CartItem, Wishlist, Order
from app import db, csrf
from app.shiprocket import check_serviceability, sync_order_status, normalize_shipment_status

logger = logging.getLogger('api')
api_bp = Blueprint('api', __name__)


# ── Shipping & Serviceability ──────────────────────────────────────────────────

@api_bp.route('/shipping/check-serviceability', methods=['GET', 'POST'])
def shipping_serviceability():
    """
    Check delivery serviceability & estimated shipping charge using Shiprocket API.
    Can receive pincode via query string or JSON/form body.
    """
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        pincode = str(data.get('pincode', '')).strip()
        weight = float(data.get('weight', 0.5) or 0.5)
        cod = int(data.get('cod', 0) or 0)
    else:
        pincode = str(request.args.get('pincode', '')).strip()
        weight = float(request.args.get('weight', 0.5) or 0.5)
        cod = int(request.args.get('cod', 0) or 0)

    # Calculate actual cart weight if user is logged in and weight not provided
    if (not weight or weight <= 0.5) and current_user.is_authenticated:
        cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
        calc_weight = sum((getattr(i.product, 'weight', 0.5) or 0.5) * i.quantity for i in cart_items if i.product)
        if calc_weight > 0:
            weight = round(calc_weight, 2)

    result = check_serviceability(delivery_pincode=pincode, weight=weight, cod=cod)
    return jsonify({
        'success': True,
        'data': result
    })


# ── Shiprocket Webhook ─────────────────────────────────────────────────────────

@api_bp.route('/shiprocket/webhook', methods=['POST'])
@csrf.exempt
def shiprocket_webhook():
    """
    Automated webhook receiver for Shiprocket tracking updates.
    Updates the Order shipment_status, status, and tracking details.
    """
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    logger.info("Received Shiprocket Webhook payload: %s", payload)

    awb = str(payload.get('awb') or payload.get('awb_code') or '').strip()
    order_id_sr = str(payload.get('order_id') or '').strip()
    shipment_id_sr = str(payload.get('shipment_id') or '').strip()
    raw_status = payload.get('current_status') or payload.get('status') or ''

    if not awb and not order_id_sr and not shipment_id_sr:
        return jsonify({'status': 'ignored', 'message': 'Missing tracking identifiers'}), 200

    # Locate order in database
    order = None
    if awb:
        order = Order.query.filter(
            (Order.awb_code == awb) | (Order.tracking_number == awb)
        ).first()

    if not order and order_id_sr:
        order = Order.query.filter(
            (Order.shiprocket_order_id == order_id_sr) | (Order.order_number == order_id_sr)
        ).first()

    if not order and shipment_id_sr:
        order = Order.query.filter_by(shiprocket_shipment_id=shipment_id_sr).first()

    if not order:
        return jsonify({'status': 'not_found', 'message': 'No matching order found'}), 200

    # Update shipment status
    norm = normalize_shipment_status(raw_status)
    order.shipment_status = norm

    if norm == 'delivered':
        order.status = 'delivered'
        if order.payment_method == 'cod':
            order.payment_status = 'paid'
    elif norm in ['shipped', 'out for delivery'] and order.status in ['pending', 'confirmed']:
        order.status = 'shipped'

    courier = payload.get('courier_name')
    if courier and not order.courier_name:
        order.courier_name = courier

    if awb and not order.awb_code:
        order.awb_code = awb
        order.tracking_number = awb
        order.tracking_url = f"https://shiprocket.co/tracking/{awb}"

    etd = payload.get('etd')
    if etd:
        order.notes = f"ETD: {etd}"

    db.session.commit()
    logger.info("Order #%s updated via Shiprocket Webhook to status: %s", order.order_number, norm)

    return jsonify({
        'status': 'success',
        'order_number': order.order_number,
        'shipment_status': order.shipment_status
    }), 200


@api_bp.route('/shiprocket/sync-active', methods=['POST'])
def sync_active_shipments():
    """
    Sync all active shipments that are currently in 'shipped' or 'out for delivery'
    or 'processing' state. Can be called periodically or by admin.
    """
    active_orders = Order.query.filter(
        Order.awb_code.isnot(None),
        Order.shipment_status.in_(['processing', 'shipped', 'out for delivery'])
    ).all()

    updated = 0
    errors = 0
    for order in active_orders:
        ok, res = sync_order_status(order)
        if ok:
            updated += 1
        else:
            errors += 1

    return jsonify({
        'success': True,
        'total_active': len(active_orders),
        'updated': updated,
        'errors': errors
    })



@api_bp.route('/cart/count')
def cart_count():
    count = 0
    if current_user.is_authenticated:
        count = CartItem.query.filter_by(user_id=current_user.id).count()
    return jsonify({'count': count})


@api_bp.route('/wishlist/count')
def wishlist_count():
    count = 0
    if current_user.is_authenticated:
        count = Wishlist.query.filter_by(user_id=current_user.id).count()
    return jsonify({'count': count})


@api_bp.route('/products/search')
def product_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    
    products = Product.query.filter(
        Product.is_active == True,
        Product.name.ilike(f'%{q}%')
    ).limit(6).all()
    
    results = []
    for p in products:
        results.append({
            'id': p.id,
            'name': p.name,
            'price': p.discounted_price,
            'image': p.primary_image or '',
            'url': f'/shop/product/{p.slug}'
        })
    
    return jsonify(results)
