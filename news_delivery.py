#!/usr/bin/env python3
import os
import json
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('delivery.log'),
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()

def mask_email(email):
    """Mask email address for logging purposes."""
    if '@' not in email:
        return email
    username, domain = email.split('@')
    masked_username = username[:2] + '*' * (len(username) - 2)
    return f"{masked_username}@{domain}"

def get_today_news():
    """Get all news from Firebase today_news collection."""
    try:
        # Try to initialize Firebase
        cred = credentials.Certificate(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        
        # Get all documents from today_news collection
        news_ref = db.collection('today_news')
        docs = news_ref.get()  # Get all documents
        news_items = []
        
        for doc in docs:
            data = doc.to_dict()
            # Extract only needed fields
            news_item = {
                'title': data['article_info']['title'],
                'chinese_title': data['article_info']['chinese_title'],
                'date': data['article_info']['date'],
                'source': data['article_info']['source'],
                'english_summary': data['english_summary'],
                'chinese_summary': data['chinese_summary']
            }
            news_items.append(news_item)
        
        if news_items:
            logging.info(f"Retrieved {len(news_items)} items from today_news collection")
            return news_items
            
    except Exception as e:
        logging.error(f"Error accessing Firebase: {e}")
        return None

def send_email(news_items):
    """Send email with news items."""
    try:
        # Email setup
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"MENA/SEA News Today - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        msg['From'] = os.getenv('EMAIL_FROM')
        
        # Get and validate recipients
        recipients_str = os.getenv('EMAIL_RECIPIENTS', '')
        if not recipients_str:
            raise ValueError("No email recipients configured")
            
        recipients = [email.strip() for email in recipients_str.split(',')]
        # Use BCC instead of To field
        msg['Bcc'] = ', '.join(recipients)
        # Set a generic To address (can be the sender's address)
        msg['To'] = os.getenv('EMAIL_FROM')
        
        # Log masked recipients for debugging
        masked_recipients = [mask_email(email) for email in recipients]
        logging.info(f"Sending email to {len(recipients)} recipients: {', '.join(masked_recipients)}")

        # Generate content
        content = []
        for item in news_items:
            content.append(f"""
                <div style="margin-bottom: 20px; padding: 15px; border: 1px solid #ddd;">
                    <h2>{item['title']}</h2>
                    <h3 style="color: #666;">{item['chinese_title']}</h3>
                    <p style="color: #888;">Source: {item['source']} | Date: {item['date']}</p>
                    <div style="margin: 10px 0;">
                        <p><strong>English Summary:</strong><br>{item['english_summary']}</p>
                        <p><strong>Chinese Summary:</strong><br>{item['chinese_summary']}</p>
                    </div>
                </div>
            """)

        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <h1>MENA/SEA News Today</h1>
                <p>Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}</p>
                {''.join(content)}
            </body>
        </html>
        """

        msg.attach(MIMEText(html, 'html'))

        # Send email
        with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
            server.starttls()
            server.login(os.getenv('SMTP_USERNAME'), os.getenv('SMTP_PASSWORD'))
            server.send_message(msg)
            
        logging.info("Email sent successfully")
        return True
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return False

if __name__ == '__main__':
    news_items = get_today_news()
    if news_items:
        send_email(news_items)
    else:
        logging.error("No news items available to send") 