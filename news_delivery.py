#!/usr/bin/env python3
import os
import json
import smtplib
import uuid
import time
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
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

# Configure Flask for production
app.config.update(
    ENV='production',
    DEBUG=False,
    TESTING=False,
    SERVER_NAME=None  # Allow any host
)

def get_today_news():
    """Retrieve news from Firestore today_news collection."""
    try:
        # Query all documents in the today_news collection
        news_ref = db.collection('today_news')
        docs = news_ref.stream()
        
        news_items = []
        for doc in docs:
            news_data = doc.to_dict()
            news_items.append(news_data)
        
        logging.info(f"Found {len(news_items)} news items in today_news collection")
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

@app.route('/health')
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now(timezone.utc).isoformat()})

@app.route('/send_emails')
def trigger_email_send():
    """Endpoint to trigger email sending."""
    try:
        news_items = get_today_news()
        if not news_items:
            msg = "No news items found in today_news collection"
            logging.warning(msg)
            return jsonify({
                'status': 'error',
                'message': msg,
                'current_time_utc': datetime.now(timezone.utc).isoformat()
            }), 404
        
        success = send_email(news_items)
        if not success:
            return jsonify({'status': 'error', 'message': 'Failed to send emails'}), 500
            
        return jsonify({
            'status': 'success',
            'message': 'Emails sent successfully',
            'news_count': len(news_items)
        })
    except Exception as e:
        logging.error(f"Error sending emails: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def start_tracking_server():
    """Start the tracking server."""
    try:
        logging.info("Starting Flask server...")
        # Note: When using 'flask run', these settings will be overridden by
        # command line arguments, but we keep them for direct script execution
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=False,
            use_reloader=False  # Important for running in GitHub Actions
        )
    except Exception as e:
        logging.error(f"Failed to start Flask server: {e}")
        raise

def create_email_content(news_items, tracking_id):
    """Create HTML content for the email with tracking."""
    if not news_items:
        return None
    
    try:
        # Start with the email header and CSS styles
        html_content = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: 'Segoe UI', Arial, sans-serif;
                    line-height: 1.6;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }}
                .email-header {{
                    background-color: #003366;
                    color: white;
                    padding: 20px;
                    text-align: center;
                    border-radius: 8px 8px 0 0;
                    margin-bottom: 20px;
                }}
                .news-item {{
                    background-color: white;
                    margin-bottom: 30px;
                    padding: 25px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .title {{
                    font-size: 20px;
                    font-weight: bold;
                    color: #003366;
                    margin-bottom: 15px;
                    border-bottom: 2px solid #eee;
                    padding-bottom: 10px;
                }}
                .summary {{
                    margin: 15px 0;
                    padding: 10px;
                    background-color: #f9f9f9;
                    border-left: 4px solid #003366;
                }}
                .summary-header {{
                    font-weight: bold;
                    color: #003366;
                    margin-bottom: 5px;
                }}
                .link {{
                    margin-top: 15px;
                }}
                .link a {{
                    color: #0066cc;
                    text-decoration: none;
                    padding: 5px 10px;
                    border: 1px solid #0066cc;
                    border-radius: 4px;
                    transition: all 0.3s ease;
                }}
                .link a:hover {{
                    background-color: #0066cc;
                    color: white;
                }}
                .timestamp {{
                    color: #666;
                    font-size: 12px;
                    margin-top: 10px;
                    font-style: italic;
                }}
                .footer {{
                    text-align: center;
                    padding: 20px;
                    color: #666;
                    font-size: 12px;
                    border-top: 1px solid #eee;
                    margin-top: 20px;
                }}
            </style>
            <script>
                // Track time spent reading
                let startTime = new Date();
                const trackingId = '{tracking_id}';  // Define tracking ID as a constant
                
                window.onbeforeunload = function() {{
                    try {{
                        let endTime = new Date();
                        let timeSpent = Math.round((endTime - startTime) / 1000);
                        // Use string concatenation instead of template literals to avoid f-string confusion
                        fetch('/track/close/' + trackingId + '?time_spent=' + timeSpent);
                    }} catch(e) {{
                        console.error('Error tracking email close:', e);
                    }}
                }};
                
                // Track link clicks
                document.addEventListener('click', function(e) {{
                    if (e.target.tagName === 'A') {{
                        try {{
                            let url = e.target.href;
                            // Use string concatenation instead of template literals to avoid f-string confusion
                            fetch('/track/click/' + trackingId + '?url=' + encodeURIComponent(url));
                        }} catch(e) {{
                            console.error('Error tracking link click:', e);
                        }}
                    }}
                }});
            </script>
        </head>
        <body>
            <div class="email-header">
                <h1>MENA/SEA Daily News - 出海中东/东南亚日报</h1>
                <p>{datetime.now(timezone.utc).strftime("%Y-%m-%d")}</p>
            </div>
        """
        
        # Add each news item
        for item in news_items:
            try:
                # Get or generate title
                article_info = item.get('article_info', {})
                english_title = article_info.get('title', 'No title')
                chinese_title = article_info.get('chinese_title', '无标题')
                if english_title == 'No title' and 'English_summary' in item:
                    # Extract first sentence from English summary as title
                    english_title = item['English_summary'].split('.')[0] + '.'
                
                html_content += f"""
                <div class="news-item">
                    <div class="title">
                        <div>{english_title}</div>
                        <div style="font-size: 0.9em;">{chinese_title}</div>
                    </div>
                    <div class="summary">
                        <div class="summary-header">English Summary:</div>
                        <p>{item.get('English_summary', 'No summary available')}</p>
                    </div>
                    <div class="summary">
                        <div class="summary-header">Chinese Summary 中文摘要:</div>
                        <p>{item.get('Chinese_summary', '暂无摘要')}</p>
                    </div>
                    <div class="link">
                        <a href="{article_info.get('url', '#')}" target="_blank">Read Full Article 阅读全文</a>
                    </div>
                    <div class="timestamp">
                        Source: {article_info.get('source', 'Unknown')}
                        <br>
                        Published: {article_info.get('date', 'Unknown date')}
                    </div>
                </div>
                """
            except Exception as e:
                logging.error(f"Error processing news item: {str(e)}")
                continue
        
        # Add tracking pixel and footer
        tracking_url = f"http://your-domain.com/track/{tracking_id}"
        html_content += f"""
            <div class="footer">
                <p>This email is automatically generated and sent by MENA/SEA News System</p>
                <p>© {datetime.now().year} All Rights Reserved</p>
            </div>
            <img src="{tracking_url}" width="1" height="1" alt="" />
        </body>
        </html>
        """
        
        return html_content
    except Exception as e:
        logging.error(f"Error creating email content: {str(e)}")
        return None

def send_email(news_items):
    """Send email with today's news."""
    if not news_items:
        logging.warning("No news items to send")
        return False
    
    try:
        # Generate unique tracking ID
        tracking_id = str(uuid.uuid4())
        logging.info(f"Generated tracking ID: {tracking_id}")
        
        # Create email content
        html_content = create_email_content(news_items, tracking_id)
        if not html_content:
            logging.error("Failed to create email content")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"MENA/SEA Daily News - 出海中东/东南亚日报 - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
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
                'news_titles': [item.get('article_info', {}).get('title') for item in news_items]
            }
            db.collection('email_sent').add(email_data)
            
            return True
            
    except Exception as e:
        logging.error(f"Error sending email: {str(e)}")
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