import unittest
import json
import gzip
from app import create_app, db
from app.models import Product, ProductImage, Category, Banner, User, Order

class Phase9MobileTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_01_viewport_and_pwa_manifest(self):
        """Test viewport meta tag with viewport-fit=cover and PWA manifest link."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('viewport-fit=cover', html)
        self.assertIn('/static/manifest.json', html)
        self.assertIn('theme-color', html)

        # Verify manifest.json
        manifest_res = self.client.get('/static/manifest.json')
        self.assertEqual(manifest_res.status_code, 200)
        data = json.loads(manifest_res.data.decode('utf-8'))
        self.assertEqual(data.get('name'), 'Vibe Seekers')
        self.assertEqual(data.get('display'), 'standalone')

    def test_02_mobile_header_and_bottom_nav(self):
        """Test sticky mobile header and mobile bottom navigation bar in base layout."""
        res = self.client.get('/')
        html = res.data.decode('utf-8')
        self.assertIn('mobile-bottom-nav', html)
        self.assertIn('id="hamburger"', html)
        self.assertIn('mobile-nav-backdrop', html)
        self.assertIn('id="mobile-nav"', html)
        # Check all 5 mobile bottom tabs
        self.assertIn('Home', html)
        self.assertIn('Shop', html)
        self.assertIn('Wishlist', html)
        self.assertIn('Cart', html)
        self.assertIn('Account', html)

    def test_03_mobile_banner_picture_tag(self):
        """Test that banners render responsive <picture> with image_url_mobile."""
        banner = Banner(
            title='Mobile Drop',
            image_url='https://example.com/desktop.jpg',
            image_url_mobile='https://example.com/mobile.jpg',
            is_active=True
        )
        db.session.add(banner)
        db.session.commit()

        res = self.client.get('/')
        html = res.data.decode('utf-8')
        self.assertIn('<picture>', html)
        self.assertIn('(max-width: 768px)', html)
        self.assertIn('https://example.com/mobile.jpg', html)

    def test_04_product_detail_sticky_bar_and_size_guide(self):
        """Test PDP sticky add to cart bar and size guide sheet."""
        prod = Product(
            name='Oversized Heavyweight Hoodie',
            slug='oversized-heavyweight-hoodie',
            price=2499,
            discount_percent=20,
            stock=15,
            is_active=True
        )
        db.session.add(prod)
        db.session.commit()

        img1 = ProductImage(product_id=prod.id, image_url='https://example.com/1.jpg')
        img2 = ProductImage(product_id=prod.id, image_url='https://example.com/2.jpg')
        db.session.add_all([img1, img2])
        db.session.commit()

        res = self.client.get(f'/shop/product/{prod.slug}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('sticky-pdp-bar', html)
        self.assertIn('triggerStickyAddToCart()', html)
        self.assertIn('size-guide-modal', html)
        self.assertIn('size-guide-sheet', html)
        self.assertIn('gallery-dots-mobile', html)

    def test_05_checkout_mobile_collapsible_summary(self):
        """Test checkout page contains collapsible order summary toggle and numeric inputs."""
        # Add item to session cart or visit checkout with empty cart
        res = self.client.get('/cart/checkout', follow_redirects=True)
        # May redirect to cart or show empty cart
        self.assertEqual(res.status_code, 200)

        # Check checkout template contents
        with open('templates/cart/checkout.html', 'r', encoding='utf-8') as f:
            checkout_html = f.read()
        self.assertIn('mobile-order-summary-toggle', checkout_html)
        self.assertIn('toggleMobileOrderSummary()', checkout_html)
        self.assertIn('checkout-summary-collapsible', checkout_html)
        self.assertIn('inputmode="numeric"', checkout_html)
        self.assertNotIn('Refund Policy', checkout_html)
        self.assertNotIn('Instant Refund', checkout_html)

    def test_06_admin_panel_mobile_navigation(self):
        """Test admin panel has mobile hamburger toggle, backdrop, and responsive rules."""
        with open('templates/admin/base_admin.html', 'r', encoding='utf-8') as f:
            admin_html = f.read()
        self.assertIn('admin-mobile-toggle', admin_html)
        self.assertIn('admin-backdrop', admin_html)
        self.assertIn('toggleAdminNav', admin_html)
        self.assertIn('@media (max-width: 860px)', admin_html)

    def test_07_static_caching_and_gzip_compression(self):
        """Test Cache-Control header on static files and gzip compression on dynamic pages."""
        res = self.client.get('/static/css/main.css')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Cache-Control', res.headers)
        self.assertIn('public', res.headers['Cache-Control'])
        self.assertIn('max-age=86400', res.headers['Cache-Control'])

        # Test Gzip compression with Accept-Encoding: gzip on home page
        res_gzip = self.client.get('/', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(res_gzip.status_code, 200)
        self.assertEqual(res_gzip.headers.get('Content-Encoding'), 'gzip')
        # Ensure payload decodes validly with gzip
        decompressed = gzip.decompress(res_gzip.data)
        self.assertTrue(len(decompressed) > 0)

    def test_08_css_mobile_first_rules(self):
        """Verify CSS contains 2-column mobile grid, safe area insets, and touch target rules."""
        with open('static/css/main.css', 'r', encoding='utf-8') as f:
            css = f.read()
        self.assertIn('grid-template-columns: repeat(2, 1fr)', css)
        self.assertIn('aspect-ratio: 3/4', css)
        self.assertIn('safe-area-inset-bottom', css)
        self.assertIn('min-height: 44px', css)
        self.assertIn('font-size: 16px !important', css)

if __name__ == '__main__':
    unittest.main()
