"""
CLI script to securely create or update an administrator account for Vibe Seekers.

Usage:
    python create_admin.py
    python create_admin.py --email admin@vibeseekers.in --password "SuperSecretPass123" --name "Main Admin"
"""
import os
import sys
import getpass
import argparse
from app import create_app, db
from app.models import User

def main():
    parser = argparse.ArgumentParser(description="Create or update an admin account for Vibe Seekers.")
    parser.add_argument('--email', help="Admin email address")
    parser.add_argument('--name', default="Admin", help="Admin display name")
    parser.add_argument('--password', help="Admin password (will prompt securely if not passed)")
    args = parser.parse_args()

    email = args.email
    if not email:
        email = input("Enter admin email address: ").strip().lower()
    else:
        email = email.strip().lower()

    if not email or '@' not in email:
        print("❌ Error: Invalid email address.")
        sys.exit(1)

    password = args.password
    if not password:
        password = getpass.getpass("Enter strong admin password: ").strip()
        confirm = getpass.getpass("Confirm admin password: ").strip()
        if password != confirm:
            print("❌ Error: Passwords do not match.")
            sys.exit(1)

    if len(password) < 8:
        print("❌ Error: Password should be at least 8 characters long.")
        sys.exit(1)

    name = args.name.strip() if args.name else "Admin"

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if user:
            print(f"ℹ️  User with email '{email}' already exists. Updating to Administrator...")
            user.is_admin = True
            user.is_email_verified = True
            user.name = name
            user.set_password(password)
            db.session.commit()
            print(f"✅ Success: Admin account '{email}' updated with new password!")
        else:
            print(f"✨ Creating new Administrator account for '{email}'...")
            admin = User(
                name=name,
                email=email,
                is_admin=True,
                is_email_verified=True
            )
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            print(f"✅ Success: New Admin account '{email}' created successfully!")

if __name__ == '__main__':
    main()

