"""
Vibe Seekers – Shiprocket Shipping Integration Service
Handles authentication, serviceability checks, order creation,
AWB generation, live tracking, and webhook/sync updates.
"""
import os
import re
import time
import logging
import requests
from datetime import datetime

logger = logging.getLogger('shiprocket')

SHIPROCKET_API_BASE = "https://apiv2.shiprocket.in/v1/external"

# In-memory cache for JWT authentication token
_cached_token = None
_token_expiry = 0


def is_configured():
    """Check if valid non-placeholder Shiprocket credentials exist in .env or settings."""
    email, password, _, _ = get_credentials()
    if not email or not password:
        return False
    if "example.com" in email or "your_shiprocket" in email or "your_shiprocket" in password:
        return False
    return True


def get_credentials():
    """
    Retrieve Shiprocket credentials strictly from environment variables / .env.
    Variables: SHIPROCKET_EMAIL, SHIPROCKET_PASSWORD, SHIPROCKET_PICKUP_LOCATION.
    Never prints or logs the password.
    """
    email = os.environ.get('SHIPROCKET_EMAIL', '').strip()
    password = os.environ.get('SHIPROCKET_PASSWORD', '').strip()
    pickup_location = os.environ.get('SHIPROCKET_PICKUP_LOCATION', '').strip()
    pickup_pincode = os.environ.get('SHIPROCKET_PICKUP_PINCODE', '').strip()

    if not pickup_location:
        pickup_location = 'Primary'
    if not pickup_pincode:
        pickup_pincode = '400001'

    return email, password, pickup_pincode, pickup_location


def get_auth_token(force_refresh=False):
    """
    Authenticate with Shiprocket API and cache the JWT token.
    Token is valid for 10 days; we refresh safely after 8 days.
    Returns (token, error_message).
    """
    global _cached_token, _token_expiry

    now = time.time()
    if not force_refresh and _cached_token and now < _token_expiry:
        return _cached_token, None

    email, password, _, _ = get_credentials()
    if not email or not password or not is_configured():
        return None, "Shiprocket credentials are not configured in .env."

    try:
        url = f"{SHIPROCKET_API_BASE}/auth/login"
        payload = {"email": email, "password": password}
        resp = requests.post(url, json=payload, timeout=12)

        if resp.status_code == 200:
            data = resp.json()
            token = data.get('token')
            if token:
                _cached_token = token
                # Cache for 8 days (691200 seconds)
                _token_expiry = now + 691200
                return _cached_token, None
            return None, "Authentication succeeded but no token was returned by Shiprocket."
        
        # Parse error message from response
        try:
            err_data = resp.json()
            msg = err_data.get('message') or f"Status {resp.status_code}"
        except Exception:
            msg = f"HTTP {resp.status_code}"
        return None, f"Shiprocket login failed: {msg}"

    except requests.exceptions.Timeout:
        return None, "Connection to Shiprocket API timed out. Please try again."
    except Exception as e:
        logger.exception("Error in get_auth_token")
        return None, f"Failed to connect to Shiprocket: {str(e)}"


def check_serviceability(delivery_pincode, weight=0.5, cod=0, pickup_pincode=None):
    """
    Check if a delivery pincode is serviceable by Shiprocket couriers
    and fetch estimated shipping charges and delivery timeframe.
    """
    delivery_pincode = str(delivery_pincode or '').strip()

    # Validate 6-digit Indian PIN code format (valid Indian PINs start with digits 1-9, e.g. 000000 is invalid)
    if not re.match(r'^[1-9][0-9]{5}$', delivery_pincode):
        return {
            'serviceable': False,
            'message': f'PIN code {delivery_pincode} is not serviceable.'
        }

    _, _, default_pickup_pin, _ = get_credentials()
    pickup_pin = str(pickup_pincode or default_pickup_pin).strip()
    if not re.match(r'^\d{6}$', pickup_pin):
        pickup_pin = '400001'

    # If Shiprocket is not configured with real credentials yet, return graceful fallback
    if not is_configured():
        return {
            'serviceable': True,
            'is_mock': True,
            'courier_name': 'Shiprocket Express',
            'estimated_days': '3-5 business days',
            'rate': 79.0,
            'cod_available': True,
            'couriers': [
                {
                    'courier_name': 'Shiprocket Surface Standard',
                    'rate': 79.0,
                    'etd': '3-5 days',
                    'cod': 1
                },
                {
                    'courier_name': 'Shiprocket Air Express',
                    'rate': 119.0,
                    'etd': '2-3 days',
                    'cod': 1
                }
            ],
            'message': f'PIN {delivery_pincode} is serviceable for standard & express delivery.'
        }

    token, err = get_auth_token()
    if not token:
        # Fallback to standard delivery so user is not blocked
        return {
            'serviceable': True,
            'is_fallback': True,
            'courier_name': 'Standard Courier',
            'estimated_days': '4-6 business days',
            'rate': 79.0,
            'message': f'PIN {delivery_pincode} accepted for delivery.'
        }

    headers = {'Authorization': f'Bearer {token}'}
    params = {
        'pickup_postcode': pickup_pin,
        'delivery_postcode': delivery_pincode,
        'weight': max(0.1, float(weight or 0.5)),
        'cod': 1 if cod else 0
    }

    try:
        url = f"{SHIPROCKET_API_BASE}/courier/serviceability/"
        resp = requests.get(url, headers=headers, params=params, timeout=12)

        if resp.status_code == 401:
            # Token might have expired, try once with fresh token
            token, _ = get_auth_token(force_refresh=True)
            if token:
                headers = {'Authorization': f'Bearer {token}'}
                resp = requests.get(url, headers=headers, params=params, timeout=12)

        if resp.status_code == 200:
            data = resp.json()
            payload = data.get('data', {})
            courier_list = payload.get('available_courier_companies', [])

            if not courier_list:
                return {
                    'serviceable': False,
                    'message': f'Sorry, PIN code {delivery_pincode} is not serviceable by our courier partners at this time.'
                }

            # Sort couriers: prefer fastest delivery, then lowest rate
            sorted_couriers = sorted(
                courier_list,
                key=lambda c: (
                    float(c.get('estimated_delivery_days') or 99),
                    float(c.get('rate') or 999)
                )
            )

            best = sorted_couriers[0]
            best_courier_name = best.get('courier_name', 'Shiprocket Partner')
            best_etd_days = best.get('estimated_delivery_days') or best.get('etd') or '3-5'
            best_rate = float(best.get('rate') or 79.0)

            formatted_couriers = []
            for c in sorted_couriers[:5]:
                formatted_couriers.append({
                    'courier_name': c.get('courier_name'),
                    'rate': float(c.get('rate') or 0),
                    'etd': c.get('etd') or f"{c.get('estimated_delivery_days', '3-5')} days",
                    'cod': bool(c.get('cod', 0))
                })

            return {
                'serviceable': True,
                'courier_name': best_courier_name,
                'estimated_days': f"{best_etd_days} business days",
                'rate': best_rate,
                'cod_available': bool(best.get('cod', 0)),
                'couriers': formatted_couriers,
                'message': f'Delivery available to {delivery_pincode} in {best_etd_days} days via {best_courier_name}.'
            }

        elif resp.status_code == 404 or resp.status_code == 422:
            return {
                'serviceable': False,
                'message': f'PIN code {delivery_pincode} is not currently serviceable for delivery.'
            }
        else:
            try:
                err_json = resp.json()
                msg = err_json.get('message', 'Delivery is not serviceable at this pincode.')
            except Exception:
                msg = 'Delivery is not serviceable at this pincode.'
            return {
                'serviceable': False,
                'message': msg
            }

    except requests.exceptions.Timeout:
        return {
            'serviceable': True,
            'is_fallback': True,
            'courier_name': 'Standard Express',
            'estimated_days': '3-5 business days',
            'rate': 79.0,
            'message': f'PIN {delivery_pincode} is active for delivery (3-5 business days).'
        }
    except Exception as e:
        logger.exception("Error during serviceability check")
        return {
            'serviceable': True,
            'is_fallback': True,
            'courier_name': 'Standard Express',
            'estimated_days': '3-5 business days',
            'rate': 79.0,
            'message': f'PIN {delivery_pincode} accepted for delivery.'
        }


def create_shiprocket_order(order, pickup_location=None):
    """
    Create a shipment order in Shiprocket and generate an AWB number.
    Updates the order model with AWB, courier name, and tracking link.
    Returns (success: bool, result_dict: dict).
    """
    from app import db

    # Check if order already has an active AWB
    if order.awb_code:
        return True, {
            'message': f'Order already shipped with AWB #{order.awb_code}',
            'awb_code': order.awb_code,
            'courier_name': order.courier_name,
            'tracking_url': order.tracking_url
        }

    _, _, default_pickup_pin, default_pickup_loc = get_credentials()
    loc_name = (pickup_location or default_pickup_loc or 'Primary').strip()

    # Calculate parcel weight & dimensions from products
    total_weight = 0.0
    max_length = 10.0
    max_breadth = 10.0
    total_height = 0.0

    items_payload = []
    for item in order.items:
        prod = item.product
        w = float(getattr(prod, 'weight', 0.5) or 0.5)
        l = float(getattr(prod, 'length', 30.0) or 30.0)
        b = float(getattr(prod, 'breadth', 20.0) or 20.0)
        h = float(getattr(prod, 'height', 5.0) or 5.0)

        total_weight += w * item.quantity
        max_length = max(max_length, l)
        max_breadth = max(max_breadth, b)
        total_height += h * item.quantity

        sku = (prod.sku if prod and prod.sku else f"VS-ITEM-{item.id}").strip()
        items_payload.append({
            "name": item.product_name,
            "sku": sku,
            "units": item.quantity,
            "selling_price": round(item.price, 2),
            "discount": 0,
            "tax": 0
        })

    # Minimum thresholds
    total_weight = max(0.1, round(total_weight, 2))
    total_height = max(2.0, min(total_height, 100.0))

    # Split customer name
    full_name = (order.shipping_name or (order.user.name if order.user else 'Customer') or 'Customer').strip()
    parts = full_name.split(' ', 1)
    first_name = parts[0] or 'Customer'
    last_name = parts[1] if len(parts) > 1 else 'Customer'

    # Customer email & phone safely resolved
    raw_email = order.shipping_email or (order.user.email if order.user else None) or 'customer@vibeseekers.in'
    customer_email = str(raw_email).strip()

    raw_phone = order.shipping_phone or (order.user.phone if order.user else None) or '9876543210'
    cleaned_digits = re.sub(r'\D', '', str(raw_phone))
    customer_phone = cleaned_digits[-10:] if len(cleaned_digits) >= 10 else '9876543210'

    # If Shiprocket is not configured with real live credentials, operate in safe demo mode
    if not is_configured():
        import random
        demo_awb = f"SR{random.randint(100000000, 999999999)}"
        demo_courier = "Shiprocket Express (Blue Dart)"
        demo_track_url = f"https://shiprocket.co/tracking/{demo_awb}"

        order.shiprocket_order_id = f"DEMO_SR_{order.id}"
        order.shiprocket_shipment_id = f"DEMO_SHIP_{order.id}"
        order.awb_code = demo_awb
        order.tracking_number = demo_awb
        order.courier_name = demo_courier
        order.tracking_url = demo_track_url
        order.shipment_status = 'shipped'
        order.status = 'shipped'
        db.session.commit()

        return True, {
            'message': 'Shipment created successfully! (Configured with demo Shiprocket credentials)',
            'awb_code': demo_awb,
            'courier_name': demo_courier,
            'tracking_url': demo_track_url,
            'is_demo': True
        }

    token, err = get_auth_token()
    if not token:
        return False, {'message': err or "Unable to authenticate with Shiprocket."}

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    order_payload = {
        "order_id": order.order_number,
        "order_date": order.created_at.strftime('%Y-%m-%d %H:%M'),
        "pickup_location": loc_name,
        "channel_id": "",
        "comment": "Vibe Seekers Website Order",
        "billing_customer_name": first_name,
        "billing_last_name": last_name,
        "billing_address": order.shipping_address or 'Customer Address',
        "billing_address_2": "",
        "billing_city": order.shipping_city or 'City',
        "billing_pincode": order.shipping_pincode or '400001',
        "billing_state": order.shipping_state or 'State',
        "billing_country": order.shipping_country or 'India',
        "billing_email": customer_email,
        "billing_phone": customer_phone,
        "shipping_is_billing": True,
        "order_items": items_payload,
        "payment_method": "COD" if order.payment_method == 'cod' else "Prepaid",
        "shipping_charges": round(order.shipping_cost, 2),
        "giftwrap_charges": 0,
        "transaction_charges": 0,
        "total_discount": round(order.discount_amount, 2),
        "sub_total": round(order.subtotal, 2),
        "length": round(max_length, 1),
        "breadth": round(max_breadth, 1),
        "height": round(total_height, 1),
        "weight": total_weight
    }

    try:
        # Step 1: Create Adhoc Order
        create_url = f"{SHIPROCKET_API_BASE}/orders/create/adhoc"
        create_resp = requests.post(create_url, json=order_payload, headers=headers, timeout=20)

        if create_resp.status_code == 401:
            token, _ = get_auth_token(force_refresh=True)
            if token:
                headers['Authorization'] = f'Bearer {token}'
                create_resp = requests.post(create_url, json=order_payload, headers=headers, timeout=20)

        create_data = create_resp.json()
        if create_resp.status_code not in (200, 201):
            err_msg = create_data.get('message') or f"Shiprocket error ({create_resp.status_code})"
            return False, {'message': f"Failed to create Shiprocket order: {err_msg}"}

        sr_order_id = str(create_data.get('order_id') or '')
        sr_shipment_id = str(create_data.get('shipment_id') or '')
        awb_code = str(create_data.get('awb_code') or '').strip()

        order.shiprocket_order_id = sr_order_id
        order.shiprocket_shipment_id = sr_shipment_id

        # Step 2: Assign AWB if not generated in create step
        courier_name = "Shiprocket Courier Partner"
        if not awb_code and sr_shipment_id:
            awb_url = f"{SHIPROCKET_API_BASE}/courier/assign/awb"
            awb_payload = {"shipment_id": int(sr_shipment_id)}
            awb_resp = requests.post(awb_url, json=awb_payload, headers=headers, timeout=20)
            if awb_resp.status_code == 200:
                awb_data = awb_resp.json()
                resp_payload = awb_data.get('response', {}).get('data', {})
                awb_code = str(resp_payload.get('awb_code') or '').strip()
                courier_name = resp_payload.get('courier_name') or courier_name

        if awb_code:
            tracking_url = f"https://shiprocket.co/tracking/{awb_code}"
            order.awb_code = awb_code
            order.tracking_number = awb_code
            order.courier_name = courier_name
            order.tracking_url = tracking_url
            order.shipment_status = 'shipped'
            order.status = 'shipped'
        else:
            order.shipment_status = 'processing'
            order.status = 'confirmed'

        db.session.commit()

        return True, {
            'message': f"Shipment generated successfully! AWB: {awb_code or 'Pending Assignment'}",
            'awb_code': awb_code,
            'courier_name': courier_name,
            'tracking_url': order.tracking_url,
            'shipment_id': sr_shipment_id
        }

    except requests.exceptions.Timeout:
        return False, {'message': 'Connection to Shiprocket API timed out. Please try again.'}
    except Exception as e:
        logger.exception("Exception in create_shiprocket_order")
        return False, {'message': f"Shipment error: {str(e)}"}


def normalize_shipment_status(status_str):
    """
    Map various Shiprocket tracking status strings into our 4 canonical statuses:
    - 'processing'
    - 'shipped'
    - 'out for delivery'
    - 'delivered'
    """
    if not status_str:
        return 'processing'

    s = str(status_str).strip().upper()

    if 'DELIVERED' in s:
        return 'delivered'
    elif 'OUT FOR DELIVERY' in s or 'OUT_FOR_DELIVERY' in s:
        return 'out for delivery'
    elif any(keyword in s for keyword in ['PICKED UP', 'IN TRANSIT', 'SHIPPED', 'REACHED', 'DISPATCHED']):
        return 'shipped'
    elif any(keyword in s for keyword in ['CANCEL', 'RTO']):
        return 'cancelled'
    else:
        return 'processing'


def track_shipment(awb_code=None, shipment_id=None):
    """
    Fetch live tracking information for a shipment from Shiprocket.
    Returns (success: bool, tracking_info: dict).
    """
    awb = str(awb_code or '').strip()
    if not awb:
        return False, {'message': 'No AWB code provided.'}

    if not is_configured() or awb.startswith('DEMO_') or awb.startswith('SR'):
        # Return structured mock tracking for demo orders
        return True, {
            'awb_code': awb,
            'current_status': 'SHIPPED',
            'normalized_status': 'shipped',
            'courier_name': 'Shiprocket Express',
            'estimated_delivery': '3 days',
            'scans': [
                {'activity': 'Order manifested and ready for pickup', 'location': 'Mumbai Hub', 'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')},
                {'activity': 'Package picked up by courier partner', 'location': 'Mumbai Hub', 'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')}
            ],
            'tracking_url': f"https://shiprocket.co/tracking/{awb}"
        }

    token, err = get_auth_token()
    if not token:
        return False, {'message': err or 'Authentication failed.'}

    headers = {'Authorization': f'Bearer {token}'}

    try:
        url = f"{SHIPROCKET_API_BASE}/courier/track/awb/{awb}"
        resp = requests.get(url, headers=headers, timeout=12)

        if resp.status_code == 200:
            data = resp.json()
            track_data = data.get('tracking_data', {})
            raw_status = track_data.get('track_status') or track_data.get('shipment_track', [{}])[0].get('current_status', 'PROCESSING')
            normalized = normalize_shipment_status(raw_status)

            scans = []
            activities = track_data.get('shipment_track_activities') or []
            for act in activities:
                scans.append({
                    'activity': act.get('activity') or act.get('status'),
                    'location': act.get('location'),
                    'date': act.get('date')
                })

            return True, {
                'awb_code': awb,
                'raw_status': raw_status,
                'normalized_status': normalized,
                'courier_name': track_data.get('shipment_track', [{}])[0].get('courier_name'),
                'etd': track_data.get('etd'),
                'scans': scans,
                'tracking_url': f"https://shiprocket.co/tracking/{awb}"
            }
        else:
            return False, {'message': f"Shiprocket tracking returned status {resp.status_code}"}

    except Exception as e:
        logger.exception("Error tracking shipment")
        return False, {'message': str(e)}


def sync_order_status(order):
    """
    Sync an order's status with Shiprocket tracking API and update the database.
    """
    from app import db

    if not order.awb_code:
        return False, "Order has not been shipped yet."

    ok, info = track_shipment(order.awb_code)
    if ok:
        norm_status = info.get('normalized_status')
        if norm_status and norm_status in ['processing', 'shipped', 'out for delivery', 'delivered']:
            order.shipment_status = norm_status
            if norm_status == 'delivered':
                order.status = 'delivered'
                if order.payment_method == 'cod':
                    order.payment_status = 'paid'
            elif norm_status in ['shipped', 'out for delivery'] and order.status in ['pending', 'confirmed']:
                order.status = 'shipped'

        if info.get('courier_name') and not order.courier_name:
            order.courier_name = info.get('courier_name')

        db.session.commit()
        return True, norm_status
    return False, info.get('message', 'Failed to fetch status')


def cancel_shiprocket_shipment(order):
    """
    Cancel an active shipment through Shiprocket's Cancel API.
    For orders that are shipped / assigned an AWB but not yet delivered.
    Returns (success: bool, message: str).
    """
    from app import db

    if not order.awb_code and not order.shiprocket_order_id and not order.shiprocket_shipment_id:
        return False, "This order does not have an active shipment to cancel."

    if order.shipment_status == 'cancelled':
        return False, "This shipment is already cancelled."

    if order.shipment_status == 'delivered':
        return False, "Delivered shipments cannot be cancelled."

    # If demo/test mode
    if not is_configured() or (order.awb_code and order.awb_code.startswith('SR') and 'DEMO' in (order.shiprocket_order_id or '')):
        cancelled_awb = order.awb_code or 'N/A'
        order.shipment_status = 'cancelled'
        order.status = 'confirmed'
        order.notes = (order.notes or '') + f" | Shipment #{cancelled_awb} cancelled on {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
        order.awb_code = None
        order.tracking_number = None
        order.tracking_url = None
        db.session.commit()
        return True, f"Shipment #{cancelled_awb} has been cancelled successfully."

    token, err = get_auth_token()
    if not token:
        return False, err or "Unable to authenticate with Shiprocket."

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    try:
        resp = None
        # 1. Attempt AWB cancellation if AWB exists
        if order.awb_code:
            url = f"{SHIPROCKET_API_BASE}/orders/cancel/shipment/awbs"
            payload = {"awbs": [str(order.awb_code).strip()]}
            resp = requests.post(url, json=payload, headers=headers, timeout=15)

            if resp.status_code == 401:
                token, _ = get_auth_token(force_refresh=True)
                if token:
                    headers['Authorization'] = f'Bearer {token}'
                    resp = requests.post(url, json=payload, headers=headers, timeout=15)

        # 2. If AWB cancellation returned non-200 or no AWB, attempt Order ID cancellation
        if not resp or resp.status_code not in (200, 201):
            if order.shiprocket_order_id:
                try:
                    sr_id = int(order.shiprocket_order_id)
                    url_order = f"{SHIPROCKET_API_BASE}/orders/cancel"
                    payload_order = {"ids": [sr_id]}
                    resp_order = requests.post(url_order, json=payload_order, headers=headers, timeout=15)
                    if resp_order.status_code in (200, 201):
                        resp = resp_order
                except (ValueError, TypeError):
                    pass

        if resp and resp.status_code in (200, 201):
            cancelled_awb = order.awb_code or 'N/A'
            order.shipment_status = 'cancelled'
            order.status = 'confirmed'
            order.notes = (order.notes or '') + f" | Shipment #{cancelled_awb} cancelled on {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
            order.awb_code = None
            order.tracking_number = None
            order.tracking_url = None
            db.session.commit()
            return True, f"Shipment #{cancelled_awb} has been cancelled successfully."
        else:
            msg = "Failed to cancel shipment with Shiprocket."
            if resp:
                try:
                    err_json = resp.json()
                    msg = err_json.get('message') or f"Shiprocket error code {resp.status_code}"
                except Exception:
                    msg = f"Shiprocket HTTP {resp.status_code}"
            return False, msg

    except requests.exceptions.Timeout:
        return False, "Connection to Shiprocket API timed out. Please try again."
    except Exception as e:
        logger.exception("Error cancelling shipment")
        return False, f"Error cancelling shipment: {str(e)}"


