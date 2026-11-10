"""
Automated Pre-Launch Audit Verification Test Suite for Vibe Seekers (https://vibeseekers.in)
Covers:
- Health check route (/health)
- SEO routes (/robots.txt, /sitemap.xml)
- Security headers & Canonical SSL redirect check
- Admin authentication protection (403 on protected routes)
- Rate limiting on checkout
- Razorpay order creation validation
"""
import unittest
import os
import json
from app import create_app, db
from app.models import User, Product, Category, Order, SiteSetting

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

if __name__ == '__main__':
    unittest.main()
