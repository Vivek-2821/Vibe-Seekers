"""
Vibe Seekers - Database Models
"""
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager


# ------------------------------------------------------------------
# User Loader
# ------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(20))
    is_admin = db.Column(db.Boolean, default=False)
    is_blocked = db.Column(db.Boolean, default=False)
    is_email_verified = db.Column(db.Boolean, default=True)
    otp_code = db.Column(db.String(256))
    otp_expiry = db.Column(db.DateTime)
    otp_attempts = db.Column(db.Integer, default=0)
    otp_resend_count = db.Column(db.Integer, default=0)
    otp_resend_window = db.Column(db.DateTime)
    first_order_used = db.Column(db.Boolean, default=False)  # Track 10% first-order coupon
    reset_token = db.Column(db.String(100))
    reset_token_expiry = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    orders = db.relationship('Order', backref='user', lazy='dynamic')
    addresses = db.relationship('Address', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    wishlist = db.relationship('Wishlist', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    reviews = db.relationship('Review', backref='user', lazy='dynamic')
    cart_items = db.relationship('CartItem', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_otp(self, otp_plain):
        self.otp_code = generate_password_hash(str(otp_plain))
        self.otp_attempts = 0

    def check_otp(self, otp_plain):
        if not self.otp_code:
            return False
        if str(self.otp_code).startswith('scrypt:') or str(self.otp_code).startswith('pbkdf2:'):
            return check_password_hash(self.otp_code, str(otp_plain))
        return self.otp_code == str(otp_plain)
    
    def get_id(self):
        return str(self.id)
    
    def __repr__(self):
        return f'<User {self.email}>'


class Address(db.Model):
    __tablename__ = 'addresses'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(150))
    address_line1 = db.Column(db.String(200), nullable=False)
    address_line2 = db.Column(db.String(200))
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    pincode = db.Column(db.String(10), nullable=False)
    country = db.Column(db.String(100), default='India')
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    image = db.Column(db.String(200))  # circular thumbnail image
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    products = db.relationship('Product', backref='category', lazy='dynamic')
    
    def __repr__(self):
        return f'<Category {self.name}>'


class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    discount_percent = db.Column(db.Float, default=0)
    stock = db.Column(db.Integer, default=0)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    
    # Flags
    is_new_arrival = db.Column(db.Boolean, default=False)
    is_trending = db.Column(db.Boolean, default=False)
    is_best_selling = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Meta
    meta_title = db.Column(db.String(200))
    meta_description = db.Column(db.String(300))
    sku = db.Column(db.String(100))
    
    # Shipping & Dimensions (Shiprocket)
    weight = db.Column(db.Float, default=0.5)      # in kg
    length = db.Column(db.Float, default=30.0)     # in cm
    breadth = db.Column(db.Float, default=20.0)    # in cm
    height = db.Column(db.Float, default=5.0)      # in cm
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    images = db.relationship('ProductImage', backref='product', lazy='dynamic', 
                             cascade='all, delete-orphan', order_by='ProductImage.sort_order')
    sizes = db.relationship('ProductSize', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    colors = db.relationship('ProductColor', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    reviews = db.relationship('Review', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    cart_items = db.relationship('CartItem', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    wishlist_items = db.relationship('Wishlist', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    order_items = db.relationship('OrderItem', backref='product', lazy='dynamic')
    
    @property
    def discounted_price(self):
        if self.discount_percent:
            return round(self.price * (1 - self.discount_percent / 100), 2)
        return self.price
    
    @property
    def primary_image(self):
        img = self.images.filter_by(is_primary=True).first()
        if not img:
            img = self.images.first()
        return img.image_url if img else None
    
    @property
    def secondary_image(self):
        imgs = self.images.order_by(ProductImage.sort_order).all()
        if len(imgs) > 1:
            return imgs[1].image_url
        return None
    
    @property
    def avg_rating(self):
        reviews = self.reviews.filter_by(is_approved=True).all()
        if not reviews:
            return 0
        return round(sum(r.rating for r in reviews) / len(reviews), 1)
    
    @property
    def review_count(self):
        return self.reviews.filter_by(is_approved=True).count()

    @property
    def total_stock(self):
        """
        Unified total stock across sizes or standalone product stock.
        If sizes are defined and any size has explicit stock > 0, return the sum of size stocks.
        Otherwise, return product.stock.
        """
        size_list = self.sizes.all()
        if size_list and any(int(s.stock or 0) > 0 for s in size_list):
            return sum(int(s.stock or 0) for s in size_list)
        return int(self.stock or 0)

    def get_size_stock(self, size_name):
        """
        Return the available stock for a given size.
        If size is not specified or product has no sizes, returns total_stock.
        If sizes exist:
          - If any size has stock > 0, returns that specific size's stock (or 0 if size not found).
          - If all sizes have 0/None stock but product.stock > 0, returns product.stock.
        """
        if not size_name:
            return self.total_stock
        size_list = self.sizes.all()
        if not size_list:
            return int(self.stock or 0)
        s_obj = next((s for s in size_list if s.size.upper() == size_name.upper()), None)
        if not s_obj:
            return 0
        has_per_size_stock = any(int(s.stock or 0) > 0 for s in size_list)
        if has_per_size_stock:
            return int(s_obj.stock or 0)
        return int(self.stock or 0)

    def is_size_available(self, size_name):
        return self.get_size_stock(size_name) > 0
    
    def __repr__(self):
        return f'<Product {self.name}>'


class ProductImage(db.Model):
    __tablename__ = 'product_images'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    image_url = db.Column(db.String(300), nullable=False)
    is_primary = db.Column(db.Boolean, default=False)
    alt_text = db.Column(db.String(200))
    sort_order = db.Column(db.Integer, default=0)


class ProductSize(db.Model):
    __tablename__ = 'product_sizes'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    size = db.Column(db.String(20), nullable=False)
    stock = db.Column(db.Integer, default=0)

    @property
    def effective_stock(self):
        """
        Effective stock for this size:
        If any size for this product has explicit stock > 0, use this size's stock.
        Otherwise fallback to product total stock if available.
        """
        if self.product:
            all_sizes = self.product.sizes.all()
            if any(int(s.stock or 0) > 0 for s in all_sizes):
                return max(0, int(self.stock or 0))
            return max(0, int(self.product.stock or 0))
        return max(0, int(self.stock or 0))

    @property
    def is_available(self):
        return self.effective_stock > 0


class ProductColor(db.Model):
    __tablename__ = 'product_colors'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    color_name = db.Column(db.String(50), nullable=False)
    color_hex = db.Column(db.String(10), nullable=False)


class Review(db.Model):
    __tablename__ = 'reviews'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1–5
    title = db.Column(db.String(200))
    body = db.Column(db.Text)
    image_url = db.Column(db.String(500), nullable=True)
    is_approved = db.Column(db.Boolean, default=True)
    is_verified_buyer = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CartItem(db.Model):
    __tablename__ = 'cart_items'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    size = db.Column(db.String(20))
    color = db.Column(db.String(50))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)


class Wishlist(db.Model):
    __tablename__ = 'wishlists'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('user_id', 'product_id'),)


class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(30), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Shipping info snapshot
    shipping_name = db.Column(db.String(100))
    shipping_phone = db.Column(db.String(20))
    shipping_email = db.Column(db.String(150))
    shipping_address = db.Column(db.Text)
    shipping_city = db.Column(db.String(100))
    shipping_state = db.Column(db.String(100))
    shipping_pincode = db.Column(db.String(10))
    shipping_country = db.Column(db.String(100), default='India')
    
    # Financials
    subtotal = db.Column(db.Float, nullable=False)
    discount_amount = db.Column(db.Float, default=0)
    coupon_code = db.Column(db.String(50))
    shipping_cost = db.Column(db.Float, default=0)
    total = db.Column(db.Float, nullable=False)
    
    # Status & Payment
    status = db.Column(db.String(30), default='pending')  
    # pending, confirmed, shipped, delivered, cancelled, refunded
    payment_method = db.Column(db.String(30), default='cod')  # cod, upi, razorpay
    payment_status = db.Column(db.String(20), default='pending')  # pending, paid, failed
    razorpay_order_id = db.Column(db.String(100))
    razorpay_payment_id = db.Column(db.String(100))
    tracking_number = db.Column(db.String(100))
    notes = db.Column(db.Text)
    utr_number = db.Column(db.String(50))   # 12-digit UPI transaction reference
    upi_note = db.Column(db.String(200))    # buyer UPI ID submitted by customer
    
    # Shiprocket Shipping Details
    shiprocket_order_id = db.Column(db.String(100))
    shiprocket_shipment_id = db.Column(db.String(100))
    courier_name = db.Column(db.String(100))
    awb_code = db.Column(db.String(100))
    tracking_url = db.Column(db.String(300))
    shipment_status = db.Column(db.String(50), default='processing')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    items = db.relationship('OrderItem', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Order {self.order_number}>'


class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_name = db.Column(db.String(200), nullable=False)  # snapshot
    product_image = db.Column(db.String(300))
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=1)
    size = db.Column(db.String(20))
    color = db.Column(db.String(50))


class Coupon(db.Model):
    __tablename__ = 'coupons'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(20), default='percent')  # percent, flat
    discount_value = db.Column(db.Float, nullable=False)
    min_order_amount = db.Column(db.Float, default=0)
    max_uses = db.Column(db.Integer, default=0)  # 0 = unlimited
    uses = db.Column(db.Integer, default=0)
    first_order_only = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    valid_from = db.Column(db.DateTime, default=datetime.utcnow)
    valid_until = db.Column(db.DateTime)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ContactMessage(db.Model):
    __tablename__ = 'contact_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class NewsletterSubscriber(db.Model):
    __tablename__ = 'newsletter_subscribers'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)


class SiteSetting(db.Model):
    __tablename__ = 'site_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Banner(db.Model):
    __tablename__ = 'banners'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    subtitle = db.Column(db.String(300))
    cta_text = db.Column(db.String(100))
    cta_url = db.Column(db.String(200))
    image_url = db.Column(db.String(300))
    image_url_mobile = db.Column(db.String(300), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
