#!/usr/bin/env python3
import os
import json
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
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

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Initialize Firebase
cred = credentials.Certificate(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
firebase_admin.initialize_app(cred)
db = firestore.client()

def get_today_news():
    """Get today's news from Firebase."""
    try:
        today = datetime.now(timezone.utc).date()
        news_ref = db.collection('today_news')
        news_items = []
        
        for doc in news_ref.stream():
            news_items.append(doc.to_dict())
        
        logging.info(f"Retrieved {len(news_items)} news items")
        return news_items
    except Exception as e:
        logging.error(f"Error getting news: {e}")
        return []

def generate_chinese_title(english_title):
    """Generate Chinese title using OpenAI."""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Translate the news title to Chinese."},
                {"role": "user", "content": f"Translate: {english_title}"}
            ],
            temperature=0.7,
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error translating title: {e}")
        return "无标题"

def send_email(news_items):
    """Send email with news items."""
    try:
        # Email setup
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"SEA News Today - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        msg['From'] = os.getenv('EMAIL_FROM')
        msg['To'] = os.getenv('EMAIL_RECIPIENTS')

        # Generate content
        content = []
        for item in news_items:
            chinese_title = generate_chinese_title(item.get('title', ''))
            content.append(f"""
                <div style="margin-bottom: 20px; padding: 15px; border: 1px solid #ddd;">
                    <h2>{item.get('title', '')}</h2>
                    <h3 style="color: #666;">{chinese_title}</h3>
                    <p>{item.get('summary', '')}</p>
                    <a href="{item.get('url', '#')}" style="color: #0066cc;">Read more</a>
                </div>
            """)

        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <h1>SEA News Today</h1>
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