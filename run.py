"""
Vibe Seekers – Application Entry Point
Run: python run.py
"""
import os
from app import create_app, db
import app.models  # Registers all models (User, Category, Product, Order, etc.) before db.create_all()
from app.models import User, SiteSetting

app = create_app()


def seed_defaults(app_instance=None):
    """Create default admin account and site settings if they don't exist."""
    target_app = app_instance or app
    with target_app.app_context():
        db.create_all()

        # Ensure OTP columns exist with proper types
        try:
            cols = [c['name'] for c in db.inspect(db.engine).get_columns('users')]
            with db.engine.connect() as conn:
                if 'otp_code' not in cols:
                    conn.execute(db.text('ALTER TABLE users ADD COLUMN otp_code VARCHAR(256)'))
                else:
                    try:
                        conn.execute(db.text('ALTER TABLE users ALTER COLUMN otp_code TYPE VARCHAR(256)'))
                    except Exception:
                        pass
                if 'otp_expiry' not in cols:
                    conn.execute(db.text('ALTER TABLE users ADD COLUMN otp_expiry TIMESTAMP'))
                if 'otp_attempts' not in cols:
                    conn.execute(db.text('ALTER TABLE users ADD COLUMN otp_attempts INTEGER DEFAULT 0'))
                if 'otp_resend_count' not in cols:
                    conn.execute(db.text('ALTER TABLE users ADD COLUMN otp_resend_count INTEGER DEFAULT 0'))
                if 'otp_resend_window' not in cols:
                    conn.execute(db.text('ALTER TABLE users ADD COLUMN otp_resend_window TIMESTAMP'))
                conn.commit()
        except Exception as e:
            pass

        try:
            admin_email = os.environ.get('ADMIN_EMAIL', 'admin@vibeseekers.in')
            admin_pass = os.environ.get('ADMIN_PASSWORD', 'Admin@1234')

            # Default admin user
            admin = User.query.filter_by(email=admin_email).first()
            if not admin:
                admin = User(
                    name='Admin',
                    email=admin_email,
                    is_admin=True,
                    is_email_verified=True
                )
                admin.set_password(admin_pass)
                db.session.add(admin)
                db.session.commit()
                print(f"✅ Default admin created → {admin_email}")
            elif not admin.is_admin:
                admin.is_admin = True
                admin.is_email_verified = True
                db.session.commit()
        except Exception:
            db.session.rollback()

        # Mark all existing users as verified and clear OTP codes (email verification removed)
        try:
            User.query.filter_by(is_email_verified=False).update({User.is_email_verified: True, User.otp_code: None, User.otp_expiry: None})
            db.session.commit()
        except Exception:
            pass

        # Ensure Coupon table has first_order_only
        try:
            coupon_cols = [c['name'] for c in db.inspect(db.engine).get_columns('coupons')]
            with db.engine.connect() as conn:
                if 'first_order_only' not in coupon_cols:
                    conn.execute(db.text('ALTER TABLE coupons ADD COLUMN first_order_only BOOLEAN DEFAULT FALSE'))
                    conn.commit()
        except Exception:
            pass

        # Ensure Review table has image_url
        try:
            review_cols = [c['name'] for c in db.inspect(db.engine).get_columns('reviews')]
            with db.engine.connect() as conn:
                if 'image_url' not in review_cols:
                    conn.execute(db.text('ALTER TABLE reviews ADD COLUMN image_url VARCHAR(500)'))
                    conn.commit()
        except Exception:
            pass

        # Ensure Banner table has image_url_mobile
        try:
            banner_cols = [c['name'] for c in db.inspect(db.engine).get_columns('banners')]
            with db.engine.connect() as conn:
                if 'image_url_mobile' not in banner_cols:
                    conn.execute(db.text('ALTER TABLE banners ADD COLUMN image_url_mobile VARCHAR(300)'))
                    conn.commit()
        except Exception:
            pass

        # Ensure Order table has payment_failure_reason
        try:
            order_cols = [c['name'] for c in db.inspect(db.engine).get_columns('orders')]
            with db.engine.connect() as conn:
                if 'payment_failure_reason' not in order_cols:
                    conn.execute(db.text('ALTER TABLE orders ADD COLUMN payment_failure_reason VARCHAR(500)'))
                    conn.commit()
        except Exception:
            pass

        # Seed VIBE10 coupon
        try:
            from app.models import Coupon
            vibe10 = Coupon.query.filter_by(code='VIBE10').first()
            if not vibe10:
                vibe10 = Coupon(
                    code='VIBE10',
                    discount_type='percentage',
                    discount_value=10.0,
                    min_order_amount=0.0,
                    max_uses=0,
                    description='10% off for VIP Vibe Seekers',
                    is_active=True
                )
                db.session.add(vibe10)
        except Exception:
            pass

        # Default site settings
        try:
            defaults = {
                'store_name': 'Vibe Seekers',
                'store_email': os.environ.get('STORE_EMAIL', 'hello@vibeseekers.in'),
                'store_phone': os.environ.get('STORE_PHONE', '+91 98604 98749'),
                'store_address': 'India',
                'legal_business_name': os.environ.get('LEGAL_BUSINESS_NAME', '[YOUR BUSINESS LEGAL NAME]'),
                'announcement_text': '🔥 FREE SHIPPING on orders above ₹999 | Use code VIBE10 for 10% off your first order!',
                'announcement_active': 'true',
                'social_instagram': 'https://www.instagram.com/vibe_seekers_09',
                'social_facebook': '',
                'social_twitter': '',
                'social_youtube': '',
                'upi_id': '',
                'razorpay_key_id': os.environ.get('RAZORPAY_KEY_ID', ''),
            }
            for key, value in defaults.items():
                if not SiteSetting.query.filter_by(key=key).first():
                    db.session.add(SiteSetting(key=key, value=value))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Ensure Jackets and Accessories are removed
        try:
            from app.models import Category
            for cat in Category.query.filter(Category.slug.in_(['jackets', 'accessories'])).all():
                for p in cat.products:
                    p.category_id = None
                db.session.delete(cat)
            db.session.commit()
        except Exception:
            db.session.rollback()

        print("✅ Database initialised.")


# Auto-seed database tables and defaults on startup (for both Gunicorn and dev)
try:
    seed_defaults()
except Exception as e:
    print(f"⚠️ Initial database setup notice: {e}")


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'true').lower() in ('true', '1', 't')
    app.run(debug=debug, host='0.0.0.0', port=port)
