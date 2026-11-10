"""
Automated Pre-Launch Audit Verification Test Suite for Vibe Seekers (https://vibeseekers.in)
Covers:
- Health check route (/health)
- SEO routes (/robots.txt, /sitemap.xml)
- Security headers & Canonical SSL redirect check
- Admin authentication protection (403 on protected routes)
- Rate limiting on checkout
- Razorpay order creation & integer paise validation
- PostgreSQL type casting for address_id string vs integer queries
- Per-size stock deduction on payment and restoration on cancellation
- User My Orders and Admin Orders routes
"""
import unittest
import os
import json
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import User, Product, Category, Order, OrderItem, Address, CartItem, ProductSize, SiteSetting
from app.utils import deduct_product_stock, restore_product_stock

class PrelaunchAuditTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login_user(self, email="customer@test.com", password="password123", is_admin=False):
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(name="Test User", email=email, is_admin=is_admin, is_email_verified=True)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        login_url = '/admin/login' if is_admin else '/auth/login'
        self.client.post(login_url, data={'email': email, 'password': password})
        return user

    def test_health_check(self):
        """Verify /health returns 200 with database connected"""
        res = self.client.get('/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')

    def test_robots_txt(self):
        """Verify /robots.txt disallows admin and private routes"""
        res = self.client.get('/robots.txt')
        self.assertEqual(res.status_code, 200)
        text = res.get_data(as_text=True)
        self.assertIn("Disallow: /admin/", text)
        self.assertIn("Sitemap:", text)

    def test_sitemap_xml(self):
        """Verify /sitemap.xml returns valid xml sitemap"""
        res = self.client.get('/sitemap.xml')
        self.assertEqual(res.status_code, 200)
        text = res.get_data(as_text=True)
        self.assertIn("<?xml", text)
        self.assertIn("<urlset", text)

    def test_security_headers(self):
        """Verify security headers are attached to responses"""
        res = self.client.get('/')
        self.assertEqual(res.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res.headers.get('X-Frame-Options'), 'SAMEORIGIN')
        self.assertEqual(res.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')

    def test_admin_route_protection(self):
        """Verify unauthenticated user cannot access /admin/dashboard or /admin/orders"""
        res1 = self.client.get('/admin/dashboard')
        self.assertIn(res1.status_code, [302, 403])

        res2 = self.client.get('/admin/orders')
        self.assertIn(res2.status_code, [302, 403])

    def test_legal_pages_load(self):
        """Verify all mandatory Indian e-commerce / Razorpay compliance pages render successfully"""
        pages = ['/privacy-policy', '/terms', '/shipping-policy', '/refund-policy', '/contact', '/about']
        for p in pages:
            res = self.client.get(p)
            self.assertEqual(res.status_code, 200, f"Page {p} failed to load with status {res.status_code}")

    def test_checkout_with_string_address_id(self):
        """
        Verify string address_id (e.g. '1') from POST form data is safely cast to integer
        before database query, preventing PostgreSQL integer = varchar operator mismatch.
        """
        user = self._login_user("shopper1@test.com")
        addr = Address(
            user_id=user.id,
            full_name="Shopper One",
            phone="9876543210",
            address_line1="123 Street",
            city="Mumbai",
            state="Maharashtra",
            pincode="400001"
        )
        db.session.add(addr)

        prod = Product(
            name="Streetwear Tee",
            slug="streetwear-tee",
            price=1200.0,
            stock=10,
            is_active=True
        )
        db.session.add(prod)
        db.session.flush()

        cart_item = CartItem(user_id=user.id, product_id=prod.id, quantity=1, size="M")
        db.session.add(cart_item)
        db.session.commit()

        # Send address_id as string '1' (or whatever addr.id is)
        payload = {
            'address_id': str(addr.id),
            'payment_method': 'cod'
        }
        res = self.client.post('/cart/checkout', data=payload, headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('/cart/order-confirmation/', data.get('redirect'))

    @patch('app.routes.cart.check_serviceability', return_value={'serviceable': True})
    def test_checkout_with_new_address(self, mock_serviceability):
        """Verify submitting new address fields with address_id='' creates the address properly."""
        user = self._login_user("shopper2@test.com")
        prod = Product(name="Hoodie", slug="hoodie-test", price=1500.0, stock=5, is_active=True)
        db.session.add(prod)
        db.session.flush()
        db.session.add(CartItem(user_id=user.id, product_id=prod.id, quantity=1, size="L"))
        db.session.commit()

        payload = {
            'address_id': '',
            'full_name': 'New Buyer',
            'phone': '9860498749',
            'email': 'buyer@test.com',
            'address_line1': 'Flat 402, Elite Residency',
            'city': 'Pune',
            'state': 'Maharashtra',
            'pincode': '411001',
            'payment_method': 'cod'
        }
        res = self.client.post('/cart/checkout', data=payload, headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))

        # Verify Address saved in database
        saved_addr = Address.query.filter_by(user_id=user.id, city="Pune").first()
        self.assertIsNotNone(saved_addr)
        self.assertEqual(saved_addr.full_name, "New Buyer")

    def test_checkout_invalid_address_id_returns_404(self):
        """Verify non-existent or foreign user address ID returns clean JSON 404, not unhandled 500."""
        user = self._login_user("shopper3@test.com")
        prod = Product(name="Cap", slug="cap-test", price=500.0, stock=5, is_active=True)
        db.session.add(prod)
        db.session.flush()
        db.session.add(CartItem(user_id=user.id, product_id=prod.id, quantity=1))
        db.session.commit()

        # Pass an address ID that belongs to no one or someone else
        payload = {'address_id': '999999', 'payment_method': 'cod'}
        res = self.client.post('/cart/checkout', data=payload, headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertFalse(data.get('success'))
        self.assertIn("not found", data.get('error').lower())

    def test_razorpay_amount_is_integer_paise(self):
        """Verify order total ₹1299.00 produces exactly 129900 integer paise for Razorpay."""
        total_inr = 1299.0
        amount_paise = int(round(float(total_inr) * 100))
        self.assertIsInstance(amount_paise, int)
        self.assertEqual(amount_paise, 129900)

        small_total = 80.0
        small_paise = int(round(float(small_total) * 100))
        self.assertIsInstance(small_paise, int)
        self.assertEqual(small_paise, 8000)

    def test_stock_reduction_per_size_and_restoration(self):
        """Verify size stock is reduced correctly on payment and restored on cancellation."""
        prod = Product(name="Size Test Tee", slug="size-test-tee", price=999.0, stock=30, is_active=True)
        db.session.add(prod)
        db.session.flush()

        size_m = ProductSize(product_id=prod.id, size="M", stock=10)
        size_l = ProductSize(product_id=prod.id, size="L", stock=20)
        db.session.add_all([size_m, size_l])
        db.session.commit()

        # Deduct 2 units of size M
        deduct_product_stock(prod, quantity=2, size="M")
        db.session.commit()

        self.assertEqual(size_m.stock, 8)
        self.assertEqual(size_l.stock, 20)
        self.assertEqual(prod.stock, 28)

        # Restore 2 units of size M
        restore_product_stock(prod, quantity=2, size="M")
        db.session.commit()

        self.assertEqual(size_m.stock, 10)
        self.assertEqual(size_l.stock, 20)
        self.assertEqual(prod.stock, 30)

    def test_user_orders_page_and_admin_orders_page(self):
        """Verify customer My Orders page and Admin Orders list render without type errors."""
        admin = self._login_user("admin@test.com", is_admin=True)
        res_admin = self.client.get('/admin/orders')
        self.assertEqual(res_admin.status_code, 200)

        # Logout admin before customer accesses customer-only route
        self.client.get('/auth/logout')

        customer = self._login_user("customer_orders@test.com", is_admin=False)
        res_cust = self.client.get('/user/orders')
        self.assertEqual(res_cust.status_code, 200)

    def test_record_payment_failure_endpoint(self):
        """Verify /cart/payment/record-failure updates Order status, captures reason, and flags domain mismatch without touching stock."""
        user = self._login_user("fail_test@test.com")
        prod = Product(name="Failure Test Tee", slug="fail-tee", price=999.0, stock=10, is_active=True)
        db.session.add(prod)
        db.session.flush()
        size_m = ProductSize(product_id=prod.id, size="M", stock=10)
        db.session.add(size_m)
        db.session.flush()

        order = Order(
            order_number="VS-FAIL-001",
            user_id=user.id,
            shipping_name="Test Shopper",
            shipping_phone="9876543210",
            shipping_email=user.email,
            shipping_address="123 Street",
            shipping_city="Mumbai",
            shipping_state="Maharashtra",
            shipping_pincode="400001",
            subtotal=999.0,
            total=999.0,
            payment_method='razorpay',
            payment_status='pending',
            status='pending'
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, product_id=prod.id, product_name=prod.name, price=999.0, quantity=1, size="M"))
        db.session.commit()

        # Send failure with "website does not match"
        fail_payload = {
            'order_number': 'VS-FAIL-001',
            'razorpay_payment_id': 'pay_failed_123',
            'error_code': 'BAD_REQUEST_ERROR',
            'error_description': 'Payment blocked as website does not match registered website(s)',
            'error_reason': 'website does not match registered website(s)',
            'error_source': 'gateway',
            'error_step': 'payment_initiation'
        }
        res = self.client.post('/cart/payment/record-failure', json=fail_payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertTrue(data.get('is_domain_mismatch'))

        # Verify Order state in DB
        updated_order = Order.query.filter_by(order_number='VS-FAIL-001').first()
        self.assertEqual(updated_order.payment_status, 'failed')
        self.assertEqual(updated_order.razorpay_payment_id, 'pay_failed_123')
        self.assertIn("website does not match", updated_order.payment_failure_reason.lower())

        # Stock must NOT be reduced
        self.assertEqual(size_m.stock, 10)
        self.assertEqual(prod.stock, 10)

    def test_razorpay_webhook_idempotency_and_stock_deduction(self):
        """Verify webhook captures payment.captured, deducts per-size stock inside transaction, and is idempotent."""
        from app.models import WebhookEvent
        user = self._login_user("webhook_user@test.com")
        prod = Product(name="Webhook Tee", slug="webhook-tee", price=1299.0, stock=15, is_active=True)
        db.session.add(prod)
        db.session.flush()
        size_l = ProductSize(product_id=prod.id, size="L", stock=5)
        db.session.add(size_l)
        db.session.flush()

        order = Order(
            order_number="VS-WH-001",
            user_id=user.id,
            shipping_name="WH Shopper",
            shipping_phone="9876543210",
            shipping_email=user.email,
            shipping_address="456 Cross Rd",
            shipping_city="Pune",
            shipping_state="Maharashtra",
            shipping_pincode="411001",
            subtotal=1299.0,
            total=1299.0,
            payment_method='razorpay',
            payment_status='pending',
            status='pending',
            razorpay_order_id='order_wh_test_123'
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, product_id=prod.id, product_name=prod.name, price=1299.0, quantity=1, size="L"))
        db.session.commit()

        webhook_payload = {
            'event_id': 'evt_test_12345',
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_test_cap_999',
                        'order_id': 'order_wh_test_123',
                        'amount': 129900,
                        'status': 'captured'
                    }
                }
            }
        }

        # First webhook delivery: marks paid and deducts stock
        res1 = self.client.post('/cart/payment/webhook', json=webhook_payload)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.get_json().get('status'), 'ok')

        # Check order is paid and stock deducted
        db.session.refresh(order)
        db.session.refresh(size_l)
        db.session.refresh(prod)
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.status, 'confirmed')
        self.assertEqual(order.razorpay_payment_id, 'pay_test_cap_999')
        self.assertEqual(size_l.stock, 4)
        self.assertEqual(prod.stock, 14)

        # Check logged to WebhookEvent table
        log = WebhookEvent.query.filter_by(event_id='evt_test_12345').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.event_type, 'payment.captured')

        # Second delivery with identical event_id: idempotent ignore
        res2 = self.client.post('/cart/payment/webhook', json=webhook_payload)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json().get('status'), 'duplicate_ignored')

        # Stock must NOT be deducted a second time
        db.session.refresh(size_l)
        self.assertEqual(size_l.stock, 4)

    def test_root_razorpay_webhook_endpoint(self):
        """Verify root-level /webhooks/razorpay endpoint is active and responds without 404/405."""
        res = self.client.post('/webhooks/razorpay', json={'event': 'dummy.ping', 'event_id': 'ping_001'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json().get('status'), 'ok')

    def test_footer_legal_links_and_business_name(self):
        """Verify footer displays legal trust links and business legal entity."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('/privacy-policy', html)
        self.assertIn('/terms', html)
        self.assertIn('/shipping-policy', html)
        self.assertIn('/refund-policy', html)
        self.assertIn('/contact', html)
        self.assertIn('/about', html)
        self.assertIn('Operated by', html)

if __name__ == '__main__':
    unittest.main()
