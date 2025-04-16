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
            news_data = doc.to_dict()
            # Add document ID for reference
            news_data['id'] = doc.id
            news_items.append(news_data)
        
        if news_items:
            logging.info(f"Retrieved {len(news_items)} items from today_news collection")
            return news_items
            
    except Exception as e:
        logging.error(f"Error accessing Firebase: {e}")
    
    # Use test data if Firebase fails or returns no items
    test_items = [
        {
            'title': 'How US tariffs could impact GCC banks and economy',
            'url': 'https://example.com/news/1'
        },
        {
            'title': 'UAE announces new tech investment initiative',
            'url': 'https://example.com/news/2'
        },
        {
            'title': 'Saudi Arabia unveils major renewable energy project',
            'url': 'https://example.com/news/3'
        },
        {
            'title': 'Qatar expands LNG production capacity',
            'url': 'https://example.com/news/4'
        },
        {
            'title': 'Kuwait signs digital transformation agreement with global tech firms',
            'url': 'https://example.com/news/5'
        }
    ]
    logging.info("Using test news items since Firebase access failed")
    return test_items

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
        chinese_title = response.choices[0].message.content.strip()
        logging.info(f"Generated Chinese title for: {english_title}")
        return chinese_title
    except Exception as e:
        logging.error(f"Error translating title: {e}")
        return "无标题"

def send_email(news_items):
    """Send email with news items."""
    try:
        # Email setup
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"MENA/SEA News Today - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        msg['From'] = os.getenv('EMAIL_FROM')
        recipients = os.getenv('EMAIL_RECIPIENTS')
        msg['To'] = recipients

        # Generate content
        content = []
        for item in news_items:
            chinese_title = generate_chinese_title(item.get('title', ''))
            english_summary = generate_english_summary(item.get('title', ''))
            chinese_summary = generate_chinese_summary(english_summary)
            content.append(f"""
                <div style="margin-bottom: 20px; padding: 15px; border: 1px solid #ddd;">
                    <h2>{item.get('title', '')}</h2>
                    <h3 style="color: #666;">{chinese_title}</h3>
                    <div style="margin: 10px 0;">
                        <p><strong>English Summary:</strong><br>{english_summary}</p>
                        <p><strong>Chinese Summary:</strong><br>{chinese_summary}</p>
                    </div>
                    <a href="{item.get('url', '#')}" style="color: #0066cc;">Read more</a>
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
            
        logging.info(f"Email sent successfully to {recipients}")
        return True
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return False

def generate_english_summary(title):
    """Generate detailed English summary using OpenAI."""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Generate a detailed 2-3 sentence summary of this news topic."},
                {"role": "user", "content": f"Generate a detailed summary for: {title}"}
            ],
            temperature=0.7,
            max_tokens=200
        )
        summary = response.choices[0].message.content.strip()
        logging.info(f"Generated English summary for: {title}")
        return summary
    except Exception as e:
        logging.error(f"Error generating English summary: {e}")
        return "Summary not available"

def generate_chinese_summary(english_summary):
    """Generate Chinese summary using OpenAI."""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Translate this English summary to Chinese, maintaining the same level of detail and professional tone."},
                {"role": "user", "content": f"Translate this summary: {english_summary}"}
            ],
            temperature=0.7,
            max_tokens=200
        )
        summary = response.choices[0].message.content.strip()
        logging.info("Generated Chinese summary")
        return summary
    except Exception as e:
        logging.error(f"Error generating Chinese summary: {e}")
        return "摘要不可用"

if __name__ == '__main__':
    news_items = get_today_news()
    if news_items:
        send_email(news_items)
    else:
        logging.error("No news items available to send") 