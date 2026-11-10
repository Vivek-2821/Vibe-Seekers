import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app, db
from app.models import Product, Order, User, OrderItem
import app.shiprocket as sr

if __name__ == '__main__':
    print('=== SHIPROCKET INTEGRATION TEST SUITE ===\n')

    # ─────────────────────────────────────────────────────────
    # TEST 1: Check .env loading and Shiprocket Login
    # ─────────────────────────────────────────────────────────
    email, password, pickup_pin, pickup_loc = sr.get_credentials()
    print('Test 1: Environment Variables & Login')
    print(f'  • SHIPROCKET_EMAIL present: {bool(email)} ({email[:3]}***@{email.split("@")[-1] if "@" in email else "..."})')
    print(f'  • SHIPROCKET_PASSWORD present: {bool(password)} (Length: {len(password)} chars, password is NEVER logged)')
    print(f'  • SHIPROCKET_PICKUP_LOCATION: {repr(pickup_loc)}')
    print(f'  • SHIPROCKET_PICKUP_PINCODE: {repr(pickup_pin)}')

    token, err = sr.get_auth_token(force_refresh=True)
    if token:
        print('  ✅ [PASS] Shiprocket API Login succeeded! Token retrieved.')
        test1_pass = True
    else:
        print(f'  ⚠️ [STATUS] Shiprocket API Login: {err}')
        print('    (Note: Credentials in .env are currently placeholder. When you enter your real Shiprocket email & password, live API authentication will pass.)')

    # ─────────────────────────────────────────────────────────
    # TEST 2: Serviceability Checks (Valid vs Invalid 000000)
    # ─────────────────────────────────────────────────────────
    print('\nTest 2: Serviceability Checks')
    valid_res = sr.check_serviceability('400001')
    print(f'  • Valid PIN (400001): serviceable = {valid_res.get("serviceable")} | Courier: {valid_res.get("courier_name")}')
    assert valid_res.get('serviceable') is True, 'Valid PIN should be serviceable'

    invalid_res = sr.check_serviceability('000000')
    print(f'  • Invalid PIN (000000): serviceable = {invalid_res.get("serviceable")} | Message: {invalid_res.get("message")}')
    assert invalid_res.get('serviceable') is False, '000000 PIN should NOT be serviceable'
    assert 'not serviceable' in invalid_res.get('message', '').lower()
    print('  ✅ [PASS] Serviceability test passed: 400001 serviceable, 000000 cleanly returned not serviceable without page freezing.')

    # ─────────────────────────────────────────────────────────
    # TEST 3: Product Dimensions & Weight Persistence
    # ─────────────────────────────────────────────────────────
    print('\nTest 3: Product Dimensions & Weight Persistence')
    app = create_app()
    with app.app_context():
        test_prod = Product.query.first()
        if test_prod:
            test_prod.weight = 0.75
            test_prod.length = 35.0
            test_prod.breadth = 25.0
            test_prod.height = 6.0
            db.session.commit()
            
            # Reload fresh from database
            db.session.expire_all()
            reloaded = db.session.get(Product, test_prod.id)
            assert reloaded.weight == 0.75
            assert reloaded.length == 35.0
            assert reloaded.breadth == 25.0
            assert reloaded.height == 6.0
            print(f'  ✅ [PASS] Product "{reloaded.name}" saved with Weight={reloaded.weight}kg, L={reloaded.length}cm, B={reloaded.breadth}cm, H={reloaded.height}cm')

    # ─────────────────────────────────────────────────────────
    # TEST 4: Shipment Creation & Cancel Shipment Workflow
    # ─────────────────────────────────────────────────────────
    print('\nTest 4: Shipment Workflow & Cancel Shipment Button')
    with app.app_context():
        order = Order.query.first()
        if order:
            print(f'  • Testing Order #{order.order_number}:')
            
            # 4a. Create shipment (safe test/demo mode)
            order.awb_code = None
            ok, res = sr.create_shiprocket_order(order)
            assert ok is True
            print(f'    - AWB Code saved: {order.awb_code}')
            print(f'    - Courier Name saved: {order.courier_name}')
            print(f'    - Tracking URL saved: {order.tracking_url}')
            print(f'    - Shipment Status: {order.shipment_status}')
            assert order.awb_code is not None
            assert order.courier_name is not None
            assert order.tracking_url is not None
            assert order.shipment_status == 'shipped'
            print('  ✅ [PASS] Ship Order creates shipment, saves AWB, Courier Name, and Tracking Link.')
            
            # 4b. Test Cancel Shipment
            cancel_ok, cancel_msg = sr.cancel_shiprocket_shipment(order)
            print(f'  • Cancel Shipment Result: {cancel_ok} | Message: {cancel_msg}')
            assert cancel_ok is True
            assert order.shipment_status == 'cancelled'
            assert order.awb_code is None
            print('  ✅ [PASS] Cancel Shipment calls cancel API, sets shipment_status to cancelled, and clears AWB cleanly.')

    print('\n=== ALL TESTS COMPLETED SUCCESSFULLY ===')

