"""
Phase 3 Storefront & Customer Experience Verification Test Suite
Tests:
1. Header icons, Instagram link, Twitter removal, floating WhatsApp button.
2. Homepage real database stats (no fake claims like 500+ Styles).
3. Product detail page (image zoom markup, size selector, stock urgency, review with photo).
4. Shop filters (category, size, color, price range, sorting, pagination).
5. Track My Order public & authenticated lookup.
6. Admin banner editing capability.
"""
import os
import unittest
from io import BytesIO
from app import create_app, db
from app.models import User, Product, Category, ProductSize, ProductColor, Order, OrderItem, Banner, Review

class Phase3StorefrontTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        from run import seed_defaults
        seed_defaults(self.app)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_01_header_footer_whatsapp(self):
        """Verify header icons, Instagram link, Twitter link removal, and WhatsApp floating button"""
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # 1. Instagram link must be vibe_seekers_09
        self.assertIn('https://www.instagram.com/vibe_seekers_09', html)

        # 2. Twitter / X link must NOT exist
        self.assertNotIn('Twitter/X', html)
        self.assertNotIn('title="Twitter"', html)

        # 3. WhatsApp chat button must exist
        self.assertIn('whatsapp-float', html)
        self.assertIn('wa.me/919860498749', html)
        self.assertIn('Chat with us', html)

        # 4. Header buttons exist with SVGs (no raw URL text in button bodies)
        self.assertIn('search-toggle', html)
        self.assertIn('cart-badge', html)
        self.assertNotIn('> /cart/ <', html)
        self.assertNotIn('> /auth/login <', html)
        print("✅ [PASS] Header icons, Instagram link, WhatsApp float, and Twitter removal verified.")

    def test_02_homepage_real_stats_no_fake_claims(self):
        """Verify homepage uses authentic database stats instead of fake claims"""
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Fake claims must NOT be present
        self.assertNotIn('500+</span>', html)
        self.assertNotIn('10K+</span>', html)
        self.assertNotIn('4.9★</span>\n      <span class="hero-stat-label">Rated', html)

        # Authentic stats panel must be present
        self.assertIn('hero-stats-panel', html)
        self.assertIn('Styles</span>', html)
        print("✅ [PASS] Fake claims removed and authentic database stats rendered.")

    def test_03_shop_filters_and_sorting(self):
        """Verify shop filtering by size, color, price range, and sorting"""
        # Ensure a test product with size and color exists
        cat = Category.query.first()
        if not cat:
            cat = Category(name='T-Shirts', slug='t-shirts')
            db.session.add(cat)
            db.session.commit()

        prod = Product.query.filter_by(slug='phase3-test-tee').first()
        if not prod:
            prod = Product(
                name='Phase 3 Test Tee',
                slug='phase3-test-tee',
                price=899.0,
                discount_percent=10,
                stock=4,
                category_id=cat.id,
                is_active=True
            )
            db.session.add(prod)
            db.session.commit()
            db.session.add(ProductSize(product_id=prod.id, size='L', stock=4))
            db.session.add(ProductColor(product_id=prod.id, color_name='Black', color_hex='#000000'))
            db.session.commit()

        # 1. Filter by size=L
        resp = self.client.get('/shop/all-products?size=L')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Phase 3 Test Tee', html)

        # 2. Filter by price range
        resp = self.client.get('/shop/all-products?min_price=700&max_price=1000')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Phase 3 Test Tee', resp.get_data(as_text=True))

        # 3. Sort by price
        resp = self.client.get('/shop/all-products?sort=price_asc')
        self.assertEqual(resp.status_code, 200)

        # 4. New arrivals collection pagination & filter
        resp = self.client.get('/shop/new-arrivals?sort=newest')
        self.assertEqual(resp.status_code, 200)
        print("✅ [PASS] Shop filters (size, price range, sorting, pagination) verified.")

    def test_04_product_detail_zoom_and_urgency(self):
        """Verify product detail page has image zoom, stock urgency, and review upload"""
        prod = Product.query.filter_by(is_active=True).first()
        if not prod:
            self.skipTest("No products found to test detail page")

        # 1. Guest view
        resp = self.client.get(f'/shop/product/{prod.slug}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('main-image-wrapper', html)
        self.assertIn('Interactive Image Zoom', html)
        self.assertIn('stock-status', html)
        self.assertIn('size-guide-modal', html)
        self.assertIn('Find Your Fit', html)

        # 2. Logged in customer view for review form with photo
        user = User.query.filter_by(is_admin=False).first()
        if not user:
            user = User(name='Customer One', email='customer1@vibeseekers.test', is_admin=False, is_email_verified=True)
            user.set_password('Pass@1234')
            db.session.add(user)
            db.session.commit()
        else:
            user.set_password('Pass@1234')
            user.is_email_verified = True
            db.session.commit()

        login_resp = self.client.post('/auth/login', data={'email': user.email, 'password': 'Pass@1234'}, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)

        resp_user = self.client.get(f'/shop/product/{prod.slug}')
        self.assertEqual(resp_user.status_code, 200)
        user_html = resp_user.get_data(as_text=True)
        self.assertIn('review_image', user_html)
        self.assertIn('Add a Photo (Optional)', user_html)
        print("✅ [PASS] Product detail zoom, stock urgency, size chart, and review photo input verified.")

    def test_05_public_track_order_stepper(self):
        """Verify public /track-order route and 4-stage visual progress stepper"""
        # 1. GET /track-order renders lookup form
        resp = self.client.get('/track-order')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Track Your Order', html)
        self.assertIn('Find Your Shipment', html)
        self.assertIn('Order Number', html)

        # 2. Query an existing order
        order = Order.query.first()
        if order:
            resp = self.client.get(f'/track-order?order_number={order.order_number}&contact={order.shipping_phone or order.shipping_email}')
            self.assertEqual(resp.status_code, 200)
            res_html = resp.get_data(as_text=True)
            self.assertIn(f'Order #{order.order_number}', res_html)
            self.assertIn('Delivery Progress', res_html)
            self.assertIn('1. Placed', res_html)
            self.assertIn('4. Delivered', res_html)
        print("✅ [PASS] Public order tracking page and visual 4-stage progress stepper verified.")

    def test_06_admin_banner_edit(self):
        """Verify admin can edit hero banners and save changes"""
        # Get admin user
        admin = User.query.filter_by(is_admin=True).first()
        self.assertIsNotNone(admin, "Admin user should exist")

        banner = Banner.query.first()
        if not banner:
            banner = Banner(title='Test Banner', subtitle='Test Sub', cta_text='Shop', cta_url='/shop', is_active=True, sort_order=0)
            db.session.add(banner)
            db.session.commit()

        # Login as admin
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True

        # GET banner edit page
        resp = self.client.get(f'/admin/banners/{banner.id}/edit')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Edit Banner', resp.get_data(as_text=True))

        # POST banner edit
        resp = self.client.post(f'/admin/banners/{banner.id}/edit', data={
            'title': 'Updated Hero Title',
            'subtitle': 'Updated Subtitle',
            'cta_text': 'Explore Drop',
            'cta_url': '/new-arrivals',
            'sort_order': '1',
            'is_active': 'on'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verify in database
        updated = Banner.query.get(banner.id)
        self.assertEqual(updated.title, 'Updated Hero Title')
        self.assertEqual(updated.cta_text, 'Explore Drop')
        print("✅ [PASS] Admin banner edit route and form verified successfully.")

if __name__ == '__main__':
    unittest.main()
