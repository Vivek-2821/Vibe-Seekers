"""
Vibe Seekers – Reusable Email Delivery Service supporting:
1. Resend API (POST https://api.resend.com/emails)
2. Brevo HTTP API (POST https://api.brevo.com/v3/smtp/email)
3. Standard SMTP (smtplib with TLS/SSL)
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from app.utils import get_site_url


def clean_env_val(key, default=""):
    """Fetch an environment variable and strip surrounding whitespace and quotes."""
    val = os.environ.get(key, default)
    if val is None:
        return default
    return str(val).strip().strip("'\"")


def get_resend_from(from_name, from_email):
    """
    Format the 'from' parameter according to Resend API requirements:
    Must follow either:
      - "email@example.com"
      - "Your Name <email@yourdomain.com>"
    If using default testing before domain verification, defaults to:
      - "Your Name <onboarding@resend.dev>"
    """
    if not from_email:
        return f"{from_name} <onboarding@resend.dev>"
    
    if '<' in from_email and '>' in from_email:
        return from_email
    
    clean_email = from_email.strip()
    # Free public domains (gmail, yahoo, etc.) cannot be used directly in Resend without domain DNS
    lower = clean_email.lower()
    if any(lower.endswith(dom) for dom in ['@gmail.com', '@yahoo.com', '@hotmail.com', '@outlook.com']):
        return f"{from_name} <onboarding@resend.dev>"
        
    return f"{from_name} <{clean_email}>"


def send_email(to_email, subject, html):
    """
    Universal email sender supporting Resend API and Brevo HTTP API.
    
    1. If RESEND_API_KEY is configured:
       POST https://api.resend.com/emails
       Headers: Authorization: Bearer <RESEND_API_KEY>
       Body: {
         "from": "Vibe Seekers <onboarding@resend.dev>",
         "to": [to_email],
         "subject": subject,
         "html": html
       }

    2. If BREVO_API_KEY is configured:
       POST https://api.brevo.com/v3/smtp/email
       Headers: api-key: <BREVO_API_KEY>
       Body: {
         "sender": {"name": from_name, "email": from_email},
         "to": [{"email": to_email}],
         "subject": subject,
         "htmlContent": html
       }
    """
    resend_api_key = clean_env_val('RESEND_API_KEY')
    brevo_api_key = clean_env_val('BREVO_API_KEY')
    from_name = clean_env_val('EMAIL_FROM_NAME', 'Vibe Seekers')
    from_email = clean_env_val('EMAIL_FROM_ADDRESS')

    # 1. Try Resend API if RESEND_API_KEY is configured
    if resend_api_key:
        formatted_from = get_resend_from(from_name, from_email)
        payload = {
            "from": formatted_from,
            "to": [to_email.strip()],
            "subject": subject,
            "html": html
        }
        try:
            res = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )
            print(f"📧 [RESEND EMAIL STATUS]: {res.status_code} {res.text}")
            if res.status_code in (200, 201, 202):
                return True
            else:
                print(f"⚠️ [RESEND NOTICE]: {res.status_code} {res.text}")
        except Exception as e:
            print(f"❌ [RESEND NETWORK ERROR]: {e}")

    # 2. Try Brevo HTTP API if BREVO_API_KEY is configured
    if brevo_api_key:
        clean_email = from_email or 'hello@vibeseekers.in'
        if '<' in clean_email and '>' in clean_email:
            clean_email = clean_email.split('<')[1].split('>')[0].strip()

        payload = {
            "sender": {
                "name": from_name,
                "email": clean_email
            },
            "to": [
                {"email": to_email.strip()}
            ],
            "subject": subject,
            "htmlContent": html
        }
        try:
            res = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": brevo_api_key,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )
            print(f"📧 [BREVO EMAIL STATUS]: {res.status_code} {res.text}")
            if res.status_code in (200, 201, 202):
                return True
        except Exception as e:
            print(f"❌ [BREVO NETWORK ERROR]: {e}")

    # 3. Try Standard SMTP if MAIL_SERVER and MAIL_USERNAME are configured
    mail_server = clean_env_val('MAIL_SERVER')
    mail_username = clean_env_val('MAIL_USERNAME')
    mail_password = clean_env_val('MAIL_PASSWORD')
    if mail_server and mail_username and mail_password:
        try:
            mail_port = int(clean_env_val('MAIL_PORT', '587'))
            use_tls = clean_env_val('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
            
            sender_addr = from_email or mail_username
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{from_name} <{sender_addr}>" if '<' not in sender_addr else sender_addr
            msg['To'] = to_email.strip()
            msg.attach(MIMEText(html, 'html'))

            if mail_port == 465:
                server = smtplib.SMTP_SSL(mail_server, mail_port, timeout=10)
            else:
                server = smtplib.SMTP(mail_server, mail_port, timeout=10)
                if use_tls:
                    server.starttls()

            server.login(mail_username, mail_password)
            server.sendmail(sender_addr, [to_email.strip()], msg.as_string())
            server.quit()
            print(f"📧 [SMTP EMAIL SUCCESS] Sent to {to_email}")
            return True
        except Exception as e:
            print(f"❌ [SMTP EMAIL ERROR]: {e}")

    if not resend_api_key and not brevo_api_key and not (mail_server and mail_username):
        print("ℹ️ [EMAIL NOTICE] No email provider configured (RESEND_API_KEY, BREVO_API_KEY, or MAIL_SERVER).")
        return False

    return False


def send_password_reset_email(recipient_email, reset_url, user_name="Valued Customer"):
    """Generates email HTML and sends the secure password reset link (valid for 30 minutes)."""
    subject = "Reset Your Vibe Seekers Password"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #080808; color: #ffffff; margin: 0; padding: 24px; }}
        .card {{ max-width: 480px; margin: 0 auto; background: #111116; border: 1px solid #232330; border-radius: 14px; padding: 36px 28px; text-align: center; }}
        .brand {{ font-size: 24px; font-weight: 900; letter-spacing: 3px; color: #DC1E1E; text-transform: uppercase; margin-bottom: 24px; }}
        .title {{ font-size: 20px; font-weight: 700; color: #ffffff; margin-bottom: 12px; }}
        .text {{ font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 24px; }}
        .btn {{ display: inline-block; background: #DC1E1E; color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 700; font-size: 15px; margin: 20px 0; }}
        .footer {{ margin-top: 32px; padding-top: 20px; border-top: 1px solid #202028; font-size: 12px; color: #64748b; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="brand">VIBE SEEKERS</div>
        <div class="title">Password Reset Request</div>
        <div class="text">
          Hey {user_name},<br>
          We received a request to reset your password. Click the button below to set a new password:
        </div>
        <a href="{reset_url}" class="btn">Reset Password</a>
        <div class="text" style="font-size:12px;color:#64748b;margin-top:16px;">
          This link will expire in <strong>30 minutes</strong>.<br>
          If you did not request a password reset, you can safely ignore this email.
        </div>
        <div class="footer">&copy; Vibe Seekers India &bull; Premium Streetwear</div>
      </div>
    </body>
    </html>
    """
    return send_email(recipient_email, subject, html_content)


def send_welcome_newsletter_email(recipient_email):
    """Generates email HTML and sends the VIP subscription confirmation."""
    subject = "Welcome to Vibe Seekers! VIP Drop Access Unlocked 🔥"
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #080808; color: #ffffff; margin: 0; padding: 24px; }
        .card { max-width: 480px; margin: 0 auto; background: #111116; border: 1px solid #232330; border-radius: 14px; padding: 36px 28px; text-align: center; }
        .brand { font-size: 24px; font-weight: 900; letter-spacing: 3px; color: #DC1E1E; text-transform: uppercase; margin-bottom: 24px; }
        .title { font-size: 22px; font-weight: 700; color: #ffffff; margin-bottom: 12px; }
        .text { font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 24px; }
        .coupon-box { background: rgba(220, 30, 30, 0.1); border: 1px dashed #DC1E1E; border-radius: 10px; padding: 18px; margin: 20px 0; }
        .coupon-code { font-family: monospace; font-size: 26px; font-weight: 800; letter-spacing: 6px; color: #ffffff; }
        .btn { display: inline-block; background: #DC1E1E; color: #ffffff; text-decoration: none; padding: 12px 28px; border-radius: 8px; font-weight: 600; font-size: 14px; margin-top: 14px; }
        .footer { margin-top: 32px; padding-top: 20px; border-top: 1px solid #202028; font-size: 12px; color: #64748b; }
      </style>
    </head>
    <body>
      <div class="card">
        <div class="brand">VIBE SEEKERS</div>
        <div class="title">You're on the VIP List! 🎉</div>
        <div class="text">
          Thanks for subscribing to Vibe Seekers. You'll now be the first to know about new drops, limited-edition collections, and exclusive sales before anyone else.
        </div>
        <div class="coupon-box">
          <div style="font-size:12px;color:#cbd5e1;text-transform:uppercase;margin-bottom:6px;">Use code at checkout for 10% off:</div>
          <div class="coupon-code">VIBE10</div>
        </div>
        <a href="{get_site_url()}/shop" class="btn">Explore Collections</a>
        <div class="footer">&copy; Vibe Seekers India &bull; Premium Streetwear<br>Unsubscribe at any time.</div>
      </div>
    </body>
    </html>
    """
    return send_email(recipient_email, subject, html_content)


def send_order_confirmation_email(order):
    """Sends a professional order confirmation email to the buyer."""
    recipient_email = order.shipping_email
    if not recipient_email:
        return False

    items_html = ""
    for item in order.items:
        size_txt = f" · Size: {item.size}" if item.size else ""
        items_html += f"""
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #232330;font-size:14px;color:#fff;">
            <strong>{item.product_name}</strong>{size_txt}<br>
            <span style="font-size:12px;color:#94a3b8;">Qty: {item.quantity}</span>
          </td>
          <td style="padding:10px 0;border-bottom:1px solid #232330;font-size:14px;text-align:right;color:#fff;">
            ₹{item.price * item.quantity:,.0f}
          </td>
        </tr>
        """

    pay_method = "Cash on Delivery (COD)" if order.payment_method == 'cod' else "Razorpay (Online Payment)"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #080808; color: #ffffff; margin: 0; padding: 24px; }}
        .card {{ max-width: 520px; margin: 0 auto; background: #111116; border: 1px solid #232330; border-radius: 14px; padding: 32px 24px; }}
        .brand {{ font-size: 22px; font-weight: 900; letter-spacing: 3px; color: #DC1E1E; text-transform: uppercase; text-align: center; margin-bottom: 20px; }}
        .title {{ font-size: 20px; font-weight: 700; color: #ffffff; text-align: center; margin-bottom: 8px; }}
        .order-badge {{ display: inline-block; background: rgba(220, 30, 30, 0.15); border: 1px solid #DC1E1E; color: #fff; padding: 4px 12px; border-radius: 6px; font-family: monospace; font-size: 14px; font-weight: bold; margin-bottom: 20px; }}
        .table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        .footer {{ margin-top: 32px; padding-top: 20px; border-top: 1px solid #202028; font-size: 12px; color: #64748b; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="brand">VIBE SEEKERS</div>
        <div class="title">Order Confirmed! 🎉</div>
        <div style="text-align:center;">
          <div class="order-badge">#{order.order_number}</div>
        </div>
        <p style="font-size:14px;color:#94a3b8;line-height:1.6;">
          Hey {order.shipping_name or 'there'},<br>
          Thank you for shopping with Vibe Seekers! Your order has been placed successfully and is being prepared for dispatch.
        </p>

        <table class="table">
          {items_html}
          <tr>
            <td style="padding:8px 0;color:#94a3b8;font-size:13px;">Subtotal</td>
            <td style="padding:8px 0;text-align:right;color:#fff;font-size:13px;">₹{order.subtotal:,.0f}</td>
          </tr>
          {f'<tr><td style="padding:8px 0;color:#22c55e;font-size:13px;">Discount ({order.coupon_code})</td><td style="padding:8px 0;text-align:right;color:#22c55e;font-size:13px;">−₹{order.discount_amount:,.0f}</td></tr>' if order.discount_amount > 0 else ''}
          <tr>
            <td style="padding:8px 0;color:#94a3b8;font-size:13px;">Shipping</td>
            <td style="padding:8px 0;text-align:right;color:#fff;font-size:13px;">{'Free' if order.shipping_cost == 0 else f'₹{order.shipping_cost:,.0f}'}</td>
          </tr>
          <tr>
            <td style="padding:12px 0;font-size:16px;font-weight:700;color:#fff;border-top:1px solid #333;">Total Paid / Payable</td>
            <td style="padding:12px 0;font-size:16px;font-weight:700;color:#DC1E1E;border-top:1px solid #333;text-align:right;">₹{order.total:,.0f}</td>
          </tr>
        </table>

        <div style="background:#181822;border-radius:8px;padding:16px;margin:20px 0;font-size:13px;line-height:1.6;color:#cbd5e1;">
          <strong>Shipping To:</strong><br>
          {order.shipping_name}<br>
          {order.shipping_address}, {order.shipping_city}, {order.shipping_state} – {order.shipping_pincode}<br>
          Phone: {order.shipping_phone}<br>
          Payment: <strong>{pay_method}</strong>
        </div>

        <div class="footer">
          Questions? Reply directly to this email or visit our store.<br>
          &copy; Vibe Seekers India &bull; Premium Streetwear
        </div>
      </div>
    </body>
    </html>
    """
    subject = f"Order Confirmed: #{order.order_number} – Vibe Seekers"
    return send_email(recipient_email, subject, html_content)


def send_admin_new_order_email(order):
    """Sends a new-order notification to the store administrator."""
    admin_email = clean_env_val('ADMIN_EMAIL') or clean_env_val('STORE_EMAIL')
    if not admin_email:
        return False

    site_url = get_site_url()
    items_summary = ""
    for item in order.items:
        size_txt = f" (Size: {item.size})" if item.size else ""
        items_summary += f"• {item.product_name}{size_txt} × {item.quantity} – ₹{item.price * item.quantity:,.0f}<br>"

    pay_method = "Cash on Delivery (COD)" if order.payment_method == 'cod' else "Razorpay Online"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:-apple-system,sans-serif;background:#0d0d12;color:#ffffff;padding:24px;">
      <div style="max-width:540px;margin:0 auto;background:#16161f;border:1px solid #2b2b3d;border-radius:12px;padding:28px;">
        <h2 style="color:#DC1E1E;margin-top:0;">🚨 New Order Received!</h2>
        <p style="font-size:16px;color:#f8fafc;">Order <strong>#{order.order_number}</strong></p>
        <div style="background:#20202e;border-radius:8px;padding:16px;margin:16px 0;font-size:14px;line-height:1.7;">
          <strong>Total Amount:</strong> ₹{order.total:,.0f}<br>
          <strong>Payment:</strong> {pay_method} ({order.payment_status.upper()})<br>
          <strong>Customer:</strong> {order.shipping_name} ({order.shipping_phone})<br>
          <strong>Email:</strong> {order.shipping_email}<br>
          <strong>Address:</strong> {order.shipping_address}, {order.shipping_city}, {order.shipping_state} - {order.shipping_pincode}
        </div>
        <h3 style="font-size:14px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">Ordered Items:</h3>
        <div style="font-size:14px;color:#e2e8f0;line-height:1.6;margin-bottom:20px;">
          {items_summary}
        </div>
        <a href="{site_url}/admin/orders/{order.id}" style="display:inline-block;background:#DC1E1E;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;font-weight:700;font-size:14px;">Open Order in Admin Panel →</a>
      </div>
    </body>
    </html>
    """
    subject = f"🚨 New Order #{order.order_number} – ₹{order.total:,.0f} ({pay_method})"
    return send_email(admin_email, subject, html_content)


def send_order_shipped_email(order):
    """Sends a shipping and tracking notification to the customer."""
    recipient_email = order.shipping_email
    if not recipient_email:
        return False

    site_url = get_site_url()
    tracking_num = order.tracking_number or order.awb_code or "Tracking will update shortly"
    courier = order.courier_name or "Courier Partner"
    tracking_link = order.tracking_url or f"{site_url}/track-order?order_number={order.order_number}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:-apple-system,sans-serif;background:#0d0d12;color:#ffffff;padding:24px;">
      <div style="max-width:540px;margin:0 auto;background:#16161f;border:1px solid #2b2b3d;border-radius:12px;padding:28px;text-align:center;">
        <div style="font-size:36px;margin-bottom:12px;">🚚</div>
        <h2 style="color:#ffffff;margin-top:0;">Your Order is on the Way!</h2>
        <p style="color:#94a3b8;font-size:14px;line-height:1.6;">
          Hey {order.shipping_name or 'there'}, exciting news! Your order <strong>#{order.order_number}</strong> has been handed over to our courier partner and is on its way to you.
        </p>
        <div style="background:#20202e;border-radius:8px;padding:18px;margin:24px 0;text-align:left;font-size:14px;line-height:1.8;">
          <strong>Courier:</strong> {courier}<br>
          <strong>Tracking Number / AWB:</strong> <code style="color:#fbbf24;font-size:15px;">{tracking_num}</code><br>
          <strong>Delivering To:</strong> {order.shipping_address}, {order.shipping_city} – {order.shipping_pincode}
        </div>
        <a href="{tracking_link}" style="display:inline-block;background:#DC1E1E;color:#ffffff;text-decoration:none;padding:14px 28px;border-radius:8px;font-weight:700;font-size:14px;margin-bottom:16px;">Track Your Shipment →</a>
        <div style="font-size:12px;color:#64748b;margin-top:24px;border-top:1px solid #252535;padding-top:16px;">
          Vibe Seekers India &bull; Premium Streetwear
        </div>
      </div>
    </body>
    </html>
    """
    subject = f"Your Vibe Seekers Order #{order.order_number} Has Shipped! 🚚"
    return send_email(recipient_email, subject, html_content)
