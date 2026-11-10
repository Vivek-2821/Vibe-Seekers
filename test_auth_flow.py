import unittest
from datetime import datetime, timedelta
from app import create_app, db
from app.models import User
from run import seed_defaults

class AuthFlowTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        seed_defaults(self.app)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_01_signup_active_and_logged_in_immediately(self):
        """User registers, account is active immediately, auto-logged in, redirected to home."""
        res = self.client.post('/auth/register', data={
            'name': 'Priya Patel',
            'email': 'priya@example.com',
            'phone': '9876543210',
            'password': 'StrongPassword123',
            'confirm_password': 'StrongPassword123'
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers['Location'], '/')

        # Check in DB
        user = User.query.filter_by(email='priya@example.com').first()
        self.assertIsNotNone(user)
        self.assertTrue(user.is_email_verified)

    def test_02_logout_and_login(self):
        """User can log out and log back in without any verification step."""
        # Create user
        user = User(name='Rahul Verma', email='rahul@example.com', is_email_verified=True)
        user.set_password('Password123')
        db.session.add(user)
        db.session.commit()

        # Login
        res = self.client.post('/auth/login', data={
            'email': 'rahul@example.com',
            'password': 'Password123'
        }, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers['Location'], '/')

        # Logout
        res_logout = self.client.get('/auth/logout', follow_redirects=False)
        self.assertEqual(res_logout.status_code, 302)

    def test_03_duplicate_email_blocked_case_insensitive(self):
        """Duplicate email registration is blocked case-insensitively."""
        # Register first user
        res1 = self.client.post('/auth/register', data={
            'name': 'First User',
            'email': 'duplicate@example.com',
            'password': 'Password123',
            'confirm_password': 'Password123'
        }, follow_redirects=True)
        self.assertIn('Welcome to Vibe Seekers', res1.data.decode('utf-8'))

        # Log out so next registration is unauthenticated
        self.client.get('/auth/logout')

        # Attempt to register with uppercase variant
        res = self.client.post('/auth/register', data={
            'name': 'Second User',
            'email': 'DUPLICATE@EXAMPLE.COM',
            'password': 'Password123',
            'confirm_password': 'Password123'
        }, follow_redirects=True)

        html = res.data.decode('utf-8')
        self.assertIn('already exists', html)
        # Ensure only 1 user exists
        count = User.query.filter(db.func.lower(User.email) == 'duplicate@example.com').count()
        self.assertEqual(count, 1)

    def test_04_weak_password_and_mismatch_rejected(self):
        """Short password (< 8 chars) or mismatched password is rejected."""
        # Weak password
        res = self.client.post('/auth/register', data={
            'name': 'Weak User',
            'email': 'weak@example.com',
            'password': 'short',
            'confirm_password': 'short'
        }, follow_redirects=True)
        html = res.data.decode('utf-8')
        self.assertIn('at least 8 characters', html)
        self.assertIsNone(User.query.filter_by(email='weak@example.com').first())

        # Mismatch
        res2 = self.client.post('/auth/register', data={
            'name': 'Mismatch User',
            'email': 'mismatch@example.com',
            'password': 'Password123',
            'confirm_password': 'DifferentPassword123'
        }, follow_redirects=True)
        html2 = res2.data.decode('utf-8')
        self.assertIn('Passwords do not match', html2)
        self.assertIsNone(User.query.filter_by(email='mismatch@example.com').first())

    def test_05_wrong_password_login_rejected(self):
        """Wrong password fails login."""
        user = User(name='Valid User', email='valid@example.com', is_email_verified=True)
        user.set_password('CorrectPassword123')
        db.session.add(user)
        db.session.commit()

        res = self.client.post('/auth/login', data={
            'email': 'valid@example.com',
            'password': 'WrongPassword999'
        }, follow_redirects=True)
        html = res.data.decode('utf-8')
        self.assertIn('Invalid email or password', html)

    def test_06_admin_login_works(self):
        """Default admin can log in and is redirected to admin dashboard."""
        res = self.client.post('/auth/login', data={
            'email': 'admin@vibeseekers.in',
            'password': 'Admin@1234'
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers['Location'], '/admin/dashboard')

    def test_07_honeypot_bot_rejection(self):
        """Honeypot field stops bot submissions silently."""
        res = self.client.post('/auth/register', data={
            'name': 'Bot Spammer',
            'email': 'spambot@example.com',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'website_url': 'http://buy-viagra-now.com'
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 302)
        # Verify no user created
        bot_user = User.query.filter_by(email='spambot@example.com').first()
        self.assertIsNone(bot_user)

    def test_08_forgot_password_30min_link(self):
        """Forgot password creates 30-minute token."""
        user = User(name='Reset Target', email='target@example.com', is_email_verified=True)
        user.set_password('OldPassword123')
        db.session.add(user)
        db.session.commit()

        res = self.client.post('/auth/forgot-password', data={'email': 'target@example.com'}, follow_redirects=False)
        self.assertEqual(res.status_code, 302)

        user_db = User.query.filter_by(email='target@example.com').first()
        self.assertIsNotNone(user_db.reset_token)
        self.assertIsNotNone(user_db.reset_token_expiry)
        # Expiry should be ~30 minutes from now (between 25 and 35 mins)
        diff = (user_db.reset_token_expiry - datetime.utcnow()).total_seconds()
        self.assertTrue(1500 < diff < 2100)

    def test_09_no_refund_in_header_and_present_in_footer(self):
        """Header contains no refund link on desktop or mobile, footer retains refund policy."""
        res = self.client.get('/')
        html = res.data.decode('utf-8')

        # Split navbar section vs footer section
        nav_start = html.find('<nav class="navbar"')
        nav_end = html.find('</nav>', nav_start)
        self.assertTrue(nav_start != -1 and nav_end != -1)
        navbar_html = html[nav_start:nav_end].lower()

        # Mobile drawer section
        mob_start = html.find('id="mobile-nav"')
        mob_end = html.find('</div>\n</div>\n\n<!-- Search Overlay -->') if html.find('</div>\n</div>\n\n<!-- Search Overlay -->') != -1 else html.find('<!-- Search Overlay -->')
        mobile_nav_html = html[mob_start:mob_end].lower()

        # Assert no refund in top header or mobile drawer
        self.assertNotIn('refund', navbar_html)
        self.assertNotIn('refund', mobile_nav_html)

        # Assert refund policy link is present in footer under Help
        footer_start = html.find('<footer class="footer"')
        self.assertTrue(footer_start != -1)
        footer_html = html[footer_start:].lower()
        self.assertIn('refund policy', footer_html)
        self.assertIn('/refund-policy', footer_html)

if __name__ == '__main__':
    unittest.main()
