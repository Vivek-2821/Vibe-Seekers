"""
Unit test to verify size buttons availability, stock synchronization, and order stock reduction.
"""
import unittest
from app import create_app, db
from app.models import Product, ProductSize, Category, User, Order, OrderItem
from app.utils import deduct_product_stock, restore_product_stock


class SizeStockTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Create category & product
        cat = Category(name='T-Shirts', slug='t-shirts')
        db.session.add(cat)
        db.session.flush()

        self.prod = Product(
            name='Test Tee',
            slug='test-tee',
            price=999.0,
            stock=3,
            category_id=cat.id,
            is_active=True
        )
        db.session.add(self.prod)
        db.session.flush()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_fallback_when_sizes_have_zero_stock_but_product_has_stock(self):
        """When product has total stock 3, but sizes are 0 (the exact bug), sizes should be available."""
        s = ProductSize(product_id=self.prod.id, size='S', stock=0)
        m = ProductSize(product_id=self.prod.id, size='M', stock=0)
        l = ProductSize(product_id=self.prod.id, size='L', stock=0)
        db.session.add_all([s, m, l])
        db.session.commit()

        self.assertEqual(self.prod.total_stock, 3)
        self.assertEqual(s.effective_stock, 3)
        self.assertTrue(s.is_available)
        self.assertTrue(m.is_available)
        self.assertTrue(l.is_available)

        # Check rendered HTML
        res = self.client.get(f'/shop/product/{self.prod.slug}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Confirm S, M, L are not struck through or disabled
        self.assertIn('⚡ Only 3 left in stock', html)
        for sz in ['S', 'M', 'L']:
            btn_snippet = [chunk for chunk in html.split('</button>') if f'data-size="{sz}"' in chunk][0]
            self.assertNotIn('disabled', btn_snippet)
            self.assertNotIn('oos', btn_snippet)

    def test_specific_size_out_of_stock(self):
        """When explicit per-size stocks exist (e.g. S=5, M=0, L=2), only M is disabled."""
        s = ProductSize(product_id=self.prod.id, size='S', stock=5)
        m = ProductSize(product_id=self.prod.id, size='M', stock=0)
        l = ProductSize(product_id=self.prod.id, size='L', stock=2)
        db.session.add_all([s, m, l])
        db.session.commit()

        self.assertEqual(self.prod.total_stock, 7)
        self.assertTrue(s.is_available)
        self.assertFalse(m.is_available)
        self.assertTrue(l.is_available)

        res = self.client.get(f'/shop/product/{self.prod.slug}')
        html = res.get_data(as_text=True)

        s_btn = [c for c in html.split('</button>') if 'data-size="S"' in c][0]
        m_btn = [c for c in html.split('</button>') if 'data-size="M"' in c][0]
        l_btn = [c for c in html.split('</button>') if 'data-size="L"' in c][0]

        self.assertNotIn('disabled', s_btn)
        self.assertNotIn('oos', s_btn)

        self.assertIn('disabled', m_btn)
        self.assertIn('oos', m_btn)

        self.assertNotIn('disabled', l_btn)
        self.assertNotIn('oos', l_btn)

    def test_stock_deduction_and_restoration(self):
        """When ordering size 'S', stock is deducted from size 'S' and product total."""
        s = ProductSize(product_id=self.prod.id, size='S', stock=5)
        m = ProductSize(product_id=self.prod.id, size='M', stock=10)
        db.session.add_all([s, m])
        db.session.commit()

        # Deduct 2 of size S
        deduct_product_stock(self.prod, 2, 'S')
        db.session.commit()

        self.assertEqual(s.stock, 3)
        self.assertEqual(m.stock, 10)
        self.assertEqual(self.prod.stock, 1)  # 3 - 2 = 1

        # Restore 2 of size S
        restore_product_stock(self.prod, 2, 'S')
        db.session.commit()

        self.assertEqual(s.stock, 5)
        self.assertEqual(self.prod.stock, 3)


if __name__ == '__main__':
    unittest.main()

