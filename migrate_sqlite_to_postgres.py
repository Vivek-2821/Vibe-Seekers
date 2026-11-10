"""
SQLite to PostgreSQL Data Migration Script for Vibe Seekers
Migrates all existing data (users, products, categories, orders, settings, etc.)
from your local SQLite database to Render's PostgreSQL database.

Usage:
    python migrate_sqlite_to_postgres.py --pg-url "postgresql://user:pass@host/dbname"
Or set the environment variable:
    set TARGET_DATABASE_URL=postgresql://user:pass@host/dbname
    python migrate_sqlite_to_postgres.py
"""
import os
import sys
import argparse
from sqlalchemy import create_engine, MetaData, Table, select, insert, text

def migrate(sqlite_path='vibe_seekers.db', pg_url=None):
    if not pg_url:
        pg_url = os.environ.get('TARGET_DATABASE_URL') or os.environ.get('DATABASE_URL')
    
    if not pg_url:
        print("❌ Error: PostgreSQL target URL not provided.")
        print("Pass --pg-url 'postgresql://...' or set TARGET_DATABASE_URL in your environment.")
        sys.exit(1)

    if pg_url.startswith('postgres://'):
        pg_url = pg_url.replace('postgres://', 'postgresql://', 1)

    # Check if local SQLite file exists
    if not os.path.exists(sqlite_path):
        alt_path = os.path.join('instance', sqlite_path)
        if os.path.exists(alt_path):
            sqlite_path = alt_path
        else:
            print(f"❌ Error: SQLite file '{sqlite_path}' not found.")
            sys.exit(1)

    print(f"📦 Source SQLite DB:     {sqlite_path}")
    print(f"🐘 Target PostgreSQL DB: {pg_url.split('@')[-1] if '@' in pg_url else pg_url}")
    print("=" * 60)

    # 1. First ensure tables exist in Postgres by initializing Flask app schema
    print("\n🛠️  Step 1: Creating target tables in PostgreSQL...")
    os.environ['DATABASE_URL'] = pg_url
    from app import create_app, db
    pg_app = create_app()
    with pg_app.app_context():
        db.create_all()
    print("✓ Tables verified and ready in PostgreSQL.")

    # 2. Connect directly via SQLAlchemy engines
    sqlite_engine = create_engine(f'sqlite:///{sqlite_path}')
    pg_engine = create_engine(pg_url)

    sqlite_meta = MetaData()
    sqlite_meta.reflect(bind=sqlite_engine)

    pg_meta = MetaData()
    pg_meta.reflect(bind=pg_engine)

    # Ordered table list to respect foreign key constraints
    TABLE_ORDER = [
        'users',
        'categories',
        'products',
        'product_images',
        'product_sizes',
        'product_colors',
        'addresses',
        'orders',
        'order_items',
        'reviews',
        'coupons',
        'banners',
        'site_settings',
        'newsletter_subscribers',
        'contact_messages',
        'wishlists',
        'cart_items'
    ]

    # Add any extra tables found
    for t_name in sqlite_meta.tables.keys():
        if t_name not in TABLE_ORDER:
            TABLE_ORDER.append(t_name)

    print("\n🚀 Step 2: Copying data table by table...")
    with sqlite_engine.connect() as src_conn, pg_engine.connect() as tgt_conn:
        # Disable foreign key constraints temporarily if possible
        for table_name in TABLE_ORDER:
            if table_name not in sqlite_meta.tables or table_name not in pg_meta.tables:
                continue

            src_table = sqlite_meta.tables[table_name]
            tgt_table = pg_meta.tables[table_name]

            # Read source rows
            rows = src_conn.execute(select(src_table)).fetchall()
            if not rows:
                print(f"  • {table_name}: 0 rows (skipped)")
                continue

            row_dicts = [dict(row._mapping) for row in rows]

            # Clear existing rows in target table to avoid duplicate primary key collisions
            tgt_conn.execute(tgt_table.delete())
            tgt_conn.commit()

            # Insert rows
            tgt_conn.execute(insert(tgt_table), row_dicts)
            tgt_conn.commit()
            print(f"  ✓ {table_name}: {len(row_dicts)} rows migrated")

        # 3. Reset PostgreSQL sequences so future auto-increment IDs work
        print("\n🔢 Step 3: Synchronizing PostgreSQL auto-increment sequences...")
        for table_name in TABLE_ORDER:
            if table_name in pg_meta.tables:
                try:
                    tgt_conn.execute(text(f"""
                        SELECT setval(pg_get_serial_sequence('{table_name}', 'id'),
                               COALESCE((SELECT MAX(id) + 1 FROM "{table_name}"), 1),
                               false);
                    """))
                    tgt_conn.commit()
                except Exception:
                    tgt_conn.rollback()

    print("\n" + "=" * 60)
    print("🎉 MIGRATION COMPLETE! All data copied successfully to PostgreSQL.")
    print("=" * 60)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Migrate SQLite to Render PostgreSQL")
    parser.add_argument('--sqlite', default='vibe_seekers.db', help='Path to SQLite database file')
    parser.add_argument('--pg-url', default=None, help='PostgreSQL connection URL')
    args = parser.parse_args()
    migrate(args.sqlite, args.pg_url)

