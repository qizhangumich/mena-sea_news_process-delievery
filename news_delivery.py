#!/usr/bin/env python3
import os
import json
import smtplib
import uuid
import time
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
import logging
from flask import Flask, request, Response, jsonify
import requests
import pytz

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('news_delivery.log'),
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()

# Initialize Firebase
cred = credentials.Certificate(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
firebase_admin.initialize_app(cred)
db = firestore.client()

# Create Flask app for tracking
app = Flask(__name__)

def get_today_news():
    """Retrieve today's news from Firestore."""
    try:
        # Get today's date in Dubai timezone (UTC+4)
        dubai_tz = pytz.timezone('Asia/Dubai')
        today = datetime.now(dubai_tz).date()
        today_str = today.strftime("%Y-%m-%d")
        
        # Query the today_news collection
        news_ref = db.collection('today_news')
        query = news_ref.where('date', '==', today_str)
        docs = query.stream()
        
        news_items = []
        for doc in docs:
            news_data = doc.to_dict()
            news_items.append(news_data)
        
        logging.info(f"Found {len(news_items)} news items for today ({today_str})")
        return news_items
    except Exception as e:
        logging.error(f"Error retrieving news: {e}")
        return []

def track_email_open(tracking_id):
    """Record email open in Firestore."""
    try:
        open_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'ip_address': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', 'Unknown'),
            'email_id': tracking_id,
            'time_spent': 0  # Will be updated when email is closed
        }
        
        # Add to email_opens collection
        db.collection('email_opens').add(open_data)
        logging.info(f"Email open tracked for ID: {tracking_id}")
    except Exception as e:
        logging.error(f"Error tracking email open: {e}")

def track_email_close(tracking_id, time_spent):
    """Record email close and time spent reading."""
    try:
        # Find the most recent open for this tracking_id
        opens = db.collection('email_opens').where('email_id', '==', tracking_id).order_by('timestamp', direction=firestore.Query.DESCENDING).limit(1).stream()
        
        for doc in opens:
            # Update the document with time spent
            doc.reference.update({
                'time_spent': time_spent,
                'closed_at': datetime.now(timezone.utc).isoformat()
            })
            logging.info(f"Email close tracked for ID: {tracking_id}, time spent: {time_spent}s")
    except Exception as e:
        logging.error(f"Error tracking email close: {e}")

def track_link_click(tracking_id, link_url):
    """Record link click in Firestore."""
    try:
        click_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'ip_address': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', 'Unknown'),
            'email_id': tracking_id,
            'link_url': link_url
        }
        
        # Add to email_clicks collection
        db.collection('email_clicks').add(click_data)
        logging.info(f"Link click tracked for ID: {tracking_id}, URL: {link_url}")
    except Exception as e:
        logging.error(f"Error tracking link click: {e}")

@app.route('/track/<tracking_id>')
def tracking_pixel(tracking_id):
    """Serve tracking pixel and record open."""
    # Record the open
    track_email_open(tracking_id)
    
    # Return a 1x1 transparent GIF
    pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x21\xF9\x04\x01\x00\x00\x00\x00\x2C\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3B'
    return Response(pixel, mimetype='image/gif')

@app.route('/track/close/<tracking_id>')
def track_close(tracking_id):
    """Record email close and time spent."""
    time_spent = request.args.get('time_spent', type=int, default=0)
    track_email_close(tracking_id, time_spent)
    return jsonify({'status': 'success'})

@app.route('/track/click/<tracking_id>')
def track_click(tracking_id):
    """Record link click."""
    link_url = request.args.get('url', '')
    track_link_click(tracking_id, link_url)
    return jsonify({'status': 'success'})

def start_tracking_server():
    """Start the tracking server in a separate thread."""
    app.run(host='0.0.0.0', port=5000)

def create_email_content(news_items, tracking_id):
    """Create HTML content for the email with tracking."""
    if not news_items:
        return None
    
    # Start with the email header
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
            .news-item {{ margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
            .title {{ font-size: 18px; font-weight: bold; color: #333; }}
            .summary {{ margin: 10px 0; }}
            .link {{ color: #0066cc; text-decoration: none; }}
            .timestamp {{ color: #666; font-size: 12px; }}
        </style>
        <script>
            // Track time spent reading
            let startTime = new Date();
            window.onbeforeunload = function() {{
                let endTime = new Date();
                let timeSpent = Math.round((endTime - startTime) / 1000);
                let trackingId = '{tracking_id}';
                fetch(`/track/close/${{trackingId}}?time_spent=${{timeSpent}}`);
            }};
            
            // Track link clicks
            document.addEventListener('click', function(e) {{
                if (e.target.tagName === 'A') {{
                    let trackingId = '{tracking_id}';
                    let url = e.target.href;
                    fetch(`/track/click/${{trackingId}}?url=${{encodeURIComponent(url)}}`);
                }}
            }});
        </script>
    </head>
    <body>
    """
    
    # Add each news item
    for item in news_items:
        html_content += f"""
        <div class="news-item">
            <div class="title">{item.get('title', 'No title')}</div>
            <div class="summary">
                <p><strong>English Summary:</strong> {item.get('English_summary', 'No summary available')}</p>
                <p><strong>Chinese Summary:</strong> {item.get('Chinese_summary', 'No summary available')}</p>
            </div>
            <div class="link">
                <a href="{item.get('url', '#')}" target="_blank">Read more</a>
            </div>
            <div class="timestamp">
                Published: {item.get('date', 'Unknown date')}
            </div>
        </div>
        """
    
    # Add tracking pixel
    tracking_url = f"http://your-domain.com/track/{tracking_id}"
    html_content += f'<img src="{tracking_url}" width="1" height="1" alt="" />'
    
    # Close the HTML
    html_content += """
    </body>
    </html>
    """
    
    return html_content

def send_email(news_items):
    """Send email with today's news."""
    if not news_items:
        logging.warning("No news items to send")
        return False
    
    try:
        # Generate unique tracking ID
        tracking_id = str(uuid.uuid4())
        
        # Create email content
        html_content = create_email_content(news_items, tracking_id)
        if not html_content:
            logging.error("Failed to create email content")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"SEA News Summary - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        msg['From'] = os.getenv('EMAIL_FROM')
        msg['To'] = os.getenv('EMAIL_RECIPIENTS')
        
        # Attach HTML content
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to SMTP server
        with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
            server.starttls()
            server.login(os.getenv('SMTP_USERNAME'), os.getenv('SMTP_PASSWORD'))
            
            # Send email
            server.send_message(msg)
            logging.info("Email sent successfully")
            
            # Record email sent with tracking ID
            email_data = {
                'tracking_id': tracking_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'recipients': os.getenv('EMAIL_RECIPIENTS').split(','),
                'news_count': len(news_items),
                'news_titles': [item.get('title') for item in news_items]
            }
            db.collection('email_sent').add(email_data)
            
            return True
            
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return False

def main():
    logging.info("Starting news delivery process")
    
    # Start tracking server in a separate thread
    tracking_thread = threading.Thread(target=start_tracking_server)
    tracking_thread.daemon = True
    tracking_thread.start()
    
    # Get today's news
    news_items = get_today_news()
    if not news_items:
        logging.warning("No news items found for today")
        return
    
    # Send email
    success = send_email(news_items)
    if success:
        logging.info("News delivery completed successfully")
    else:
        logging.error("News delivery failed")

if __name__ == "__main__":
    main() 