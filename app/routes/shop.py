"""
Shop routes: All Products, Product Detail, Category pages
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user
from app.models import Product, Category, Review, Wishlist
from app import db

shop_bp = Blueprint('shop', __name__)


@shop_bp.route('/')
def shop_index():
    return redirect(url_for('shop.all_products'))


def get_filtered_products(base_filter_func=None):
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    query = Product.query.filter_by(is_active=True)
    if base_filter_func:
        query = base_filter_func(query)
    
    category_slug = request.args.get('category')
    size_filter = request.args.get('size')
    color_filter = request.args.get('color')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    sort = request.args.get('sort', 'newest')
    search_q = request.args.get('q', '').strip()
    
    selected_category = None
    if category_slug:
        selected_category = Category.query.filter_by(slug=category_slug).first()
        if selected_category:
            query = query.filter_by(category_id=selected_category.id)
    
    if size_filter:
        from app.models import ProductSize
        query = query.join(ProductSize).filter(ProductSize.size == size_filter)
    if color_filter:
        from app.models import ProductColor
        query = query.join(ProductColor).filter(ProductColor.color_name == color_filter)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    if search_q:
        query = query.filter(Product.name.ilike(f'%{search_q}%'))
    
    # Sorting
    if sort == 'price_asc':
        query = query.order_by(Product.price.asc())
    elif sort == 'price_desc':
        query = query.order_by(Product.price.desc())
    elif sort == 'name':
        query = query.order_by(Product.name.asc())
    else:
        query = query.order_by(Product.created_at.desc())
    
    products = query.paginate(page=page, per_page=per_page, error_out=False)
    categories = Category.query.filter_by(is_active=True).all()
    
    from app.models import ProductColor
    available_sizes = ['XS', 'S', 'M', 'L', 'XL', 'XXL']
    raw_colors = db.session.query(ProductColor.color_name).distinct().all()
    available_colors = [c[0] for c in raw_colors if c[0]]
    
    return {
        'products': products,
        'categories': categories,
        'selected_category': selected_category,
        'available_sizes': available_sizes,
        'available_colors': available_colors,
        'selected_size': size_filter,
        'selected_color': color_filter,
        'min_price': min_price,
        'max_price': max_price,
        'sort': sort,
        'search_q': search_q
    }


@shop_bp.route('/all-products')
def all_products():
    data = get_filtered_products()
    return render_template('shop/all_products.html',
                           current_endpoint='shop.all_products',
                           title='All Products – Vibe Seekers',
                           **data)


@shop_bp.route('/new-arrivals')
def new_arrivals():
    data = get_filtered_products(lambda q: q.filter(Product.is_new_arrival == True))
    return render_template('shop/all_products.html',
                           section_title='New Arrivals',
                           current_endpoint='shop.new_arrivals',
                           title='New Arrivals – Vibe Seekers',
                           **data)


@shop_bp.route('/trending')
def trending():
    data = get_filtered_products(lambda q: q.filter(Product.is_trending == True))
    return render_template('shop/all_products.html',
                           section_title='Trending Now',
                           current_endpoint='shop.trending',
                           title='Trending – Vibe Seekers',
                           **data)


@shop_bp.route('/best-selling')
def best_selling():
    data = get_filtered_products(lambda q: q.filter(Product.is_best_selling == True))
    return render_template('shop/all_products.html',
                           section_title='Best Selling',
                           current_endpoint='shop.best_selling',
                           title='Best Selling – Vibe Seekers',
                           **data)


@shop_bp.route('/category/<slug>')
def category(slug):
    cat = Category.query.filter_by(slug=slug, is_active=True).first_or_404()
    data = get_filtered_products(lambda q: q.filter(Product.category_id == cat.id))
    data['selected_category'] = cat
    return render_template('shop/all_products.html',
                           section_title=cat.name,
                           current_endpoint='shop.category',
                           endpoint_kwargs={'slug': slug},
                           title=f'{cat.name} – Vibe Seekers',
                           **data)


@shop_bp.route('/product/<slug>')
def product_detail(slug):
    product = Product.query.filter_by(slug=slug, is_active=True).first_or_404()
    reviews = product.reviews.filter_by(is_approved=True).order_by(Review.created_at.desc()).all()
    
    # Is in wishlist?
    in_wishlist = False
    if current_user.is_authenticated:
        in_wishlist = Wishlist.query.filter_by(
            user_id=current_user.id, product_id=product.id).first() is not None
    
    # Related products
    related = Product.query.filter(
        Product.category_id == product.category_id,
        Product.id != product.id,
        Product.is_active == True
    ).limit(4).all()
    
    images = product.images.order_by('sort_order').all()
    sizes = product.sizes.all()
    colors = product.colors.all()
    
    return render_template('shop/product_detail.html',
                           product=product,
                           reviews=reviews,
                           in_wishlist=in_wishlist,
                           related=related,
                           images=images,
                           sizes=sizes,
                           colors=colors,
                           title=f'{product.name} – Vibe Seekers')


@shop_bp.route('/product/<int:product_id>/review', methods=['POST'])
def submit_review(product_id):
    from flask_login import login_required
    if not current_user.is_authenticated:
        flash('Please log in to leave a review.', 'error')
        return redirect(url_for('auth.login'))
    
    product = Product.query.get_or_404(product_id)
    
    # Check if user already reviewed
    existing = Review.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if existing:
        flash('You\'ve already reviewed this product.', 'info')
        return redirect(url_for('shop.product_detail', slug=product.slug))
    
    rating = request.form.get('rating', type=int)
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '').strip()
    
    if not rating or rating < 1 or rating > 5:
        flash('Please select a valid rating.', 'error')
        return redirect(url_for('shop.product_detail', slug=product.slug))
    
    # Check if verified buyer
    from app.models import Order, OrderItem
    is_verified = OrderItem.query.join(Order).filter(
        Order.user_id == current_user.id,
        OrderItem.product_id == product_id,
        Order.status.in_(['delivered', 'shipped'])
    ).first() is not None
    
    image_url = None
    if 'review_image' in request.files and request.files['review_image'].filename:
        from app.utils import save_image
        image_url = save_image(request.files['review_image'], 'reviews')
    
    review = Review(
        product_id=product_id,
        user_id=current_user.id,
        rating=rating,
        title=title,
        body=body,
        image_url=image_url,
        is_verified_buyer=is_verified
    )
    db.session.add(review)
    db.session.commit()
    
    flash('Thank you for your review!', 'success')
    return redirect(url_for('shop.product_detail', slug=product.slug))
