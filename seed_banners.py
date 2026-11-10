"""Seed 4 cinematic banners into the Vibe Seekers database."""
from app import create_app, db
from app.models import Banner

app = create_app()

BANNERS = [
    {
        'title': 'New Collection',
        'subtitle': 'Wear The Vibe',
        'cta_text': 'Shop Now →',
        'cta_url': '/shop',
        'image_url': '/static/images/banner1.png',
        'sort_order': 1,
    },
    {
        'title': 'Wear The Vibe',
        'subtitle': 'Premium Streetwear',
        'cta_text': 'Explore Now →',
        'cta_url': '/shop/new-arrivals',
        'image_url': '/static/images/banner2.png',
        'sort_order': 2,
    },
    {
        'title': 'New Arrivals',
        'subtitle': 'Just Dropped',
        'cta_text': 'View Arrivals →',
        'cta_url': '/shop/new-arrivals',
        'image_url': '/static/images/banner3.png',
        'sort_order': 3,
    },
    {
        'title': 'Free Shipping',
        'subtitle': 'On Orders Above ₹999',
        'cta_text': 'Shop The Look →',
        'cta_url': '/shop',
        'image_url': '/static/images/banner4.png',
        'sort_order': 4,
    },
]

with app.app_context():
    # Clear existing banners
    Banner.query.delete()
    db.session.commit()

    for b in BANNERS:
        banner = Banner(
            title=b['title'],
            subtitle=b['subtitle'],
            cta_text=b['cta_text'],
            cta_url=b['cta_url'],
            image_url=b['image_url'],
            is_active=True,
            sort_order=b['sort_order'],
        )
        db.session.add(banner)

    db.session.commit()
    print(f"✅ {len(BANNERS)} banners seeded successfully!")
    for b in Banner.query.order_by(Banner.sort_order).all():
        print(f"  [{b.sort_order}] {b.title} → {b.image_url}")
