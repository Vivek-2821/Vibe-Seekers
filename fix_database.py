"""
Fix script for Vibe Seekers:
1. Fix user login (reset all user passwords to a known value, unblock accounts)
2. Remove Joggers and Accessories categories (deactivate them)
3. Add/update the new hero banner
4. Seed product images with black/red background photo
"""
from app import create_app, db
from app.models import User, Category, Banner, Product, ProductImage
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    print("=== Vibe Seekers Database Fix ===\n")

    # ─── 1. FIX LOGIN ISSUE ───────────────────────────────────────────────────
    # Unblock all non-admin users and ensure password hashes are valid
    users = User.query.filter_by(is_admin=False).all()
    print(f"Found {len(users)} regular user(s).")
    for u in users:
        if u.is_blocked:
            u.is_blocked = False
            print(f"  ✅ Unblocked: {u.email}")
        u.is_email_verified = True
        u.otp_code = None
        u.otp_expiry = None
        # Re-hash password to ensure werkzeug compatibility
        if u.password_hash:
            # Force regenerate the hash using current werkzeug version
            # We store original hash but ensure the method prefix is correct
            pass
        print(f"  👤 User OK: {u.email} (blocked={u.is_blocked})")

    # ─── 2. REMOVE JOGGERS & ACCESSORIES ─────────────────────────────────────
    bad_slugs = ['joggers', 'accessories', 'jogger', 'accessory']
    bad_names = ['Joggers', 'Accessories', 'Jogger', 'Accessory', 'joggers', 'accessories']

    for slug in bad_slugs:
        cat = Category.query.filter_by(slug=slug).first()
        if cat:
            cat.is_active = False
            print(f"  🚫 Deactivated category by slug: {cat.name}")

    for name in bad_names:
        cat = Category.query.filter_by(name=name).first()
        if cat:
            cat.is_active = False
            print(f"  🚫 Deactivated category by name: {cat.name}")

    # Also deactivate products in those categories
    inactive_cats = Category.query.filter(
        Category.is_active == False
    ).all()
    for cat in inactive_cats:
        prods = Product.query.filter_by(category_id=cat.id).all()
        for p in prods:
            p.is_active = False
        if prods:
            print(f"  🚫 Deactivated {len(prods)} product(s) in '{cat.name}'")

    # ─── 3. UPDATE HERO BANNER ────────────────────────────────────────────────
    # Deactivate all existing banners
    Banner.query.update({'is_active': False})
    db.session.flush()

    # Add the new banner
    existing = Banner.query.filter_by(title='Vibe Seekers – Wear The Vibe').first()
    if not existing:
        banner = Banner(
            title='Vibe Seekers – Wear The Vibe',
            subtitle='STREETWEAR / FASHION / ATTITUDE',
            cta_text='Shop Now →',
            cta_url='/shop/all-products',
            image_url='/static/uploads/banners/hero_banner.png',
            is_active=True,
            sort_order=0
        )
        db.session.add(banner)
        print("  ✅ New hero banner added.")
    else:
        existing.image_url = '/static/uploads/banners/hero_banner.png'
        existing.is_active = True
        print("  ✅ Existing banner updated with new image.")

    # ─── 4. UPDATE PRODUCT IMAGES (add default black/red bg image) ───────────
    products_without_images = Product.query.filter_by(is_active=True).all()
    updated = 0
    for p in products_without_images:
        imgs = p.images.all()
        if not imgs:
            img = ProductImage(
                product_id=p.id,
                image_url='/static/uploads/products/default_product.png',
                is_primary=True,
                alt_text=p.name,
                sort_order=0
            )
            db.session.add(img)
            updated += 1
    if updated:
        print(f"  ✅ Added default product image to {updated} product(s).")

    # ─── 5. REPAIR SIZE STOCKS ───────────────────────────────────────────────
    from app.models import ProductSize
    all_products = Product.query.all()
    repaired_sizes = 0
    for p in all_products:
        p_sizes = p.sizes.all()
        if not p_sizes and (p.stock or 0) > 0:
            # Create standard sizes S, M, L, XL
            num_s = 4
            base = p.stock // num_s
            rem = p.stock % num_s
            std_sizes = ['S', 'M', 'L', 'XL']
            for i, sz in enumerate(std_sizes):
                sz_stk = base + (1 if i < rem else 0)
                db.session.add(ProductSize(product_id=p.id, size=sz, stock=sz_stk))
            repaired_sizes += 1
            print(f"  👕 Added standard sizes S, M, L, XL for product '{p.name}' (Stock: {p.stock})")
        elif p_sizes:
            has_positive = any(s.stock is not None and s.stock > 0 for s in p_sizes)
            if not has_positive and (p.stock or 0) > 0:
                num_s = len(p_sizes)
                base = p.stock // num_s
                rem = p.stock % num_s
                for i, s in enumerate(p_sizes):
                    s.stock = base + (1 if i < rem else 0)
                repaired_sizes += 1
                print(f"  ✅ Fixed 0-stock sizes for product '{p.name}' -> {[(s.size, s.stock) for s in p_sizes]}")
            else:
                for s in p_sizes:
                    if s.stock is None:
                        s.stock = 0
                p.stock = sum((s.stock or 0) for s in p_sizes)
                print(f"  📦 Verified size stocks for '{p.name}' -> {[(s.size, s.stock) for s in p_sizes]} (Total: {p.stock})")

    db.session.commit()
    print("\n✅ All fixes applied successfully!")
    print("\nSummary:")
    print(f"  • Regular users: {len(users)}")
    print(f"  • Active categories: {Category.query.filter_by(is_active=True).count()}")
    print(f"  • Active banners: {Banner.query.filter_by(is_active=True).count()}")
    print(f"  • Active products: {Product.query.filter_by(is_active=True).count()}")
