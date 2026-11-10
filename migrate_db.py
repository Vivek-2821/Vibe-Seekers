"""
Safe SQLite migration script for Vibe Seekers.
Adds any missing columns to the existing database without losing data.
Run: python migrate_db.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'vibe_seekers.db')

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}")
    print("Trying alternative path...")
    DB_PATH = os.path.join(os.path.dirname(__file__), 'vibe_seekers.db')
    if not os.path.exists(DB_PATH):
        print("Database not found. Please run 'python run.py' first to create it.")
        exit(1)

print(f"Found database: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def column_exists(table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cursor.fetchall()]
    return column in cols

def add_column_if_missing(table, column, col_type, default=None):
    if not column_exists(table, column):
        if default is not None:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}"
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
        cursor.execute(sql)
        print(f"  ✅ Added column: {table}.{column}")
    else:
        print(f"  ✓  Already exists: {table}.{column}")

print("\n=== Vibe Seekers DB Migration ===\n")

# Orders table migrations
print("→ orders table:")
add_column_if_missing('orders', 'shipping_email', 'VARCHAR(150)')
add_column_if_missing('orders', 'utr_number', 'VARCHAR(50)')
add_column_if_missing('orders', 'upi_note', 'VARCHAR(200)')
add_column_if_missing('orders', 'razorpay_order_id', 'VARCHAR(100)')
add_column_if_missing('orders', 'razorpay_payment_id', 'VARCHAR(100)')
add_column_if_missing('orders', 'tracking_number', 'VARCHAR(100)')
add_column_if_missing('orders', 'notes', 'TEXT')
add_column_if_missing('orders', 'shiprocket_order_id', 'VARCHAR(100)')
add_column_if_missing('orders', 'shiprocket_shipment_id', 'VARCHAR(100)')
add_column_if_missing('orders', 'courier_name', 'VARCHAR(100)')
add_column_if_missing('orders', 'awb_code', 'VARCHAR(100)')
add_column_if_missing('orders', 'tracking_url', 'VARCHAR(300)')
add_column_if_missing('orders', 'shipment_status', 'VARCHAR(50)', "'processing'")

# Addresses table migrations
print("\n→ addresses table:")
add_column_if_missing('addresses', 'email', 'VARCHAR(150)')

# Users table migrations
print("\n→ users table:")
add_column_if_missing('users', 'first_order_used', 'BOOLEAN', 0)
add_column_if_missing('users', 'reset_token', 'VARCHAR(100)')
add_column_if_missing('users', 'reset_token_expiry', 'DATETIME')
add_column_if_missing('users', 'is_email_verified', 'BOOLEAN', 1)

# Products table migrations
print("\n→ products table:")
add_column_if_missing('products', 'weight', 'FLOAT', 0.5)
add_column_if_missing('products', 'length', 'FLOAT', 30.0)
add_column_if_missing('products', 'breadth', 'FLOAT', 20.0)
add_column_if_missing('products', 'height', 'FLOAT', 5.0)
add_column_if_missing('products', 'meta_title', 'VARCHAR(200)')
add_column_if_missing('products', 'meta_description', 'VARCHAR(300)')
add_column_if_missing('products', 'sku', 'VARCHAR(100)')
add_column_if_missing('products', 'updated_at', 'DATETIME')

# Product images migrations
print("\n→ product_images table:")
add_column_if_missing('product_images', 'alt_text', 'VARCHAR(200)')

# Reviews migrations
print("\n→ reviews table:")
add_column_if_missing('reviews', 'is_verified_buyer', 'BOOLEAN', 0)

# Site settings
print("\n→ site_settings table:")
add_column_if_missing('site_settings', 'description', 'VARCHAR(200)')

conn.commit()
conn.close()

print("\n✅ All migrations applied successfully!")
print("\nYou can now start the app with: python run.py")
