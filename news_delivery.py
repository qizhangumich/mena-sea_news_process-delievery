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
from flask import Flask, request, Response, jsonify, redirect
import requests
import pytz
from openai import OpenAI

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Initialize OpenAI client with error handling
openai_api_key = os.getenv('OPENAI_API_KEY')
if not openai_api_key:
    logging.warning("OPENAI_API_KEY not found in environment variables")
    client = None
else:
    try:
        client = OpenAI(api_key=openai_api_key)
        logging.info("OpenAI client initialized successfully")
    except Exception as e:
        logging.error(f"Error initializing OpenAI client: {str(e)}")
        client = None

# Initialize Firebase
cred = credentials.Certificate(json.loads(os.getenv('GOOGLE_APPLICATION_CREDENTIALS')))
firebase_admin.initialize_app(cred)
db = firestore.client()

def get_today_news():
    """Retrieve today's news items from Firestore."""
    try:
        # Get today's date in UTC
        today = datetime.now(timezone.utc).date()
        
        # Query Firestore for today's news
        news_ref = db.collection('today_news')
        news_items = []
        
        for doc in news_ref.stream():
            doc_data = doc.to_dict()
            # Convert Firestore timestamp to datetime
            if 'timestamp' in doc_data:
                doc_date = doc_data['timestamp'].date()
                if doc_date == today:
                    news_items.append(doc_data)
        
        logging.info(f"Retrieved {len(news_items)} news items for today")
        return news_items
        
    except Exception as e:
        logging.error(f"Error retrieving today's news: {str(e)}")
        return []

def send_email(news_items):
    """Send email with news items."""
    try:
        # Email configuration
        smtp_server = os.getenv('SMTP_SERVER')
        smtp_port = int(os.getenv('SMTP_PORT'))
        smtp_username = os.getenv('SMTP_USERNAME')
        smtp_password = os.getenv('SMTP_PASSWORD')
        email_from = os.getenv('EMAIL_FROM')
        email_recipients = os.getenv('EMAIL_RECIPIENTS').split(',')
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"SEA News Today - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        msg['From'] = email_from
        msg['To'] = ', '.join(email_recipients)
        
        # Generate tracking ID
        tracking_id = str(uuid.uuid4())
        
        # Create email content
        html_content = create_email_content(news_items, tracking_id)
        msg.attach(MIMEText(html_content, 'html'))
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(email_from, email_recipients, msg.as_string())
        
        # Log email sent
        email_data = {
            'timestamp': datetime.now(timezone.utc),
            'tracking_id': tracking_id,
            'recipients': email_recipients,
            'news_count': len(news_items)
        }
        db.collection('email_sent').add(email_data)
        
        logging.info(f"Email sent successfully to {len(email_recipients)} recipients")
        return True
        
    except Exception as e:
        logging.error(f"Error sending email: {str(e)}")
        return False

def create_email_content(news_items, tracking_id):
    """Create HTML content for the email."""
    try:
        # Generate Chinese titles for all news items
        for item in news_items:
            if 'title' in item and not item.get('chinese_title'):
                item['chinese_title'] = generate_chinese_title(item['title'])
        
        # Create tracking pixel
        tracking_pixel = f'<img src="http://localhost:5000/track/{tracking_id}" width="1" height="1" style="display:none">'
        
        # Create HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .news-item {{ margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                .title {{ font-size: 18px; font-weight: bold; margin-bottom: 10px; }}
                .chinese-title {{ color: #666; margin-bottom: 10px; }}
                .summary {{ margin-bottom: 10px; }}
                .link {{ color: #0066cc; text-decoration: none; }}
                .link:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h1>SEA News Today</h1>
            <p>Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}</p>
            
            {''.join([
                f'''
                <div class="news-item">
                    <div class="title">{item['title']}</div>
                    <div class="chinese-title">{item.get('chinese_title', '无标题')}</div>
                    <div class="summary">{item.get('summary', 'No summary available')}</div>
                    <a href="http://localhost:5000/track/click/{tracking_id}?url={item.get('url', '')}" class="link">Read more</a>
                </div>
                '''
                for item in news_items
            ])}
            
            {tracking_pixel}
            
            <script>
                // Track time spent reading
                let startTime = new Date();
                window.onbeforeunload = function() {{
                    let endTime = new Date();
                    let timeSpent = Math.round((endTime - startTime) / 1000);
                    fetch(`http://localhost:5000/track/close/{tracking_id}?time_spent=${{timeSpent}}`);
                }};
            </script>
        </body>
        </html>
        """
        
        return html_content
        
    except Exception as e:
        logging.error(f"Error creating email content: {str(e)}")
        return None

# Initialize Flask app for tracking
app = Flask(__name__)

# Configure Flask for production
app.config.update(
    ENV='production',
    DEBUG=False,
    TESTING=False,
    SERVER_NAME=None  # Allow any host
)

def track_email_open(tracking_id):
    """Record email open in Firestore."""
    try:
        # Get the email ID from the tracking ID
        email_id = tracking_id.split('_')[0]
        
        # Log the open in Firestore
        open_data = {
            'timestamp': datetime.now(timezone.utc),
            'email_id': email_id,
            'tracking_id': tracking_id,
            'ip': request.remote_addr,
            'user_agent': request.user_agent.string,
            'time_spent': 0  # Will be updated when email is closed
        }
        
        db.collection('email_opens').add(open_data)
        logging.info(f"Tracked email open for email {email_id}")
        
        # Return a transparent 1x1 pixel
        return Response(
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
            mimetype='image/png'
        )
        
    except Exception as e:
        logging.error(f"Error tracking email open: {str(e)}")
        return Response(status=500)

def track_email_close(tracking_id, time_spent):
    """Record email close and time spent reading in Firestore."""
    try:
        # Get the email ID from the tracking ID
        email_id = tracking_id.split('_')[0]
        
        # Find the most recent open record for this email
        opens_ref = db.collection('email_opens')
        query = opens_ref.where('email_id', '==', email_id).order_by('timestamp', direction=firestore.Query.DESCENDING).limit(1)
        docs = query.stream()
        
        for doc in docs:
            # Update the time spent reading
            doc.reference.update({
                'time_spent': int(time_spent),
                'closed_at': datetime.now(timezone.utc)
            })
            logging.info(f"Updated time spent reading for email {email_id}: {time_spent} seconds")
            return jsonify({'status': 'success'})
        
        logging.warning(f"No open record found for email {email_id}")
        return jsonify({'status': 'error', 'message': 'No open record found'}), 404
        
    except Exception as e:
        logging.error(f"Error tracking email close: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def track_link_click(tracking_id):
    """Record link click in Firestore."""
    try:
        # Get the email ID from the tracking ID
        email_id = tracking_id.split('_')[0]
        
        # Log the click in Firestore
        click_data = {
            'timestamp': datetime.now(timezone.utc),
            'email_id': email_id,
            'tracking_id': tracking_id,
            'ip': request.remote_addr,
            'user_agent': request.user_agent.string,
            'url': request.args.get('url', '')
        }
        
        db.collection('email_clicks').add(click_data)
        logging.info(f"Tracked link click for email {email_id}")
        
        # Redirect to the actual URL
        return redirect(request.args.get('url', '/'))
        
    except Exception as e:
        logging.error(f"Error tracking link click: {str(e)}")
        return redirect('/')

@app.route('/track/<tracking_id>')
def track_open(tracking_id):
    """Track email open."""
    return track_email_open(tracking_id)

@app.route('/track/close/<tracking_id>')
def track_close(tracking_id):
    """Track email close and time spent reading."""
    time_spent = request.args.get('time_spent', 0)
    return track_email_close(tracking_id, time_spent)

@app.route('/track/click/<tracking_id>')
def track_click(tracking_id):
    """Track link click."""
    return track_link_click(tracking_id)

@app.route('/health')
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})

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

@app.route('/test_title_generation')
def test_title_generation():
    """Test endpoint for Chinese title generation."""
    test_title = "How US tariffs could impact GCC banks and economy"
    try:
        chinese_title = generate_chinese_title(test_title)
        return jsonify({
            'status': 'success',
            'english_title': test_title,
            'chinese_title': chinese_title
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

def main():
    """Main function to run the application."""
    try:
        # Start the Flask app
        app.run(host='0.0.0.0', port=5000)
    except Exception as e:
        logging.error(f"Error running application: {str(e)}")
        raise

def start_tracking_server():
    """Start the tracking server in a separate thread."""
    try:
        logging.info("Starting tracking server")
        app.run(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        logging.error(f"Error starting tracking server: {str(e)}")
        raise

def generate_chinese_title(english_title):
    """Generate a Chinese title using OpenAI."""
    if not client:
        logging.warning("OpenAI client not available, returning default Chinese title")
        return "无标题"  # Return "No title" in Chinese
        
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional news translator. Translate the given English news title to Chinese. The translation should be concise, accurate, and maintain the original meaning. Use formal Chinese language suitable for news headlines."
                },
                {
                    "role": "user",
                    "content": f"Please translate this news title to Chinese: {english_title}"
                }
            ],
            temperature=0.7,
            max_tokens=100
        )
        
        chinese_title = response.choices[0].message.content.strip()
        logging.info(f"Generated Chinese title: {chinese_title}")
        return chinese_title
        
    except Exception as e:
        logging.error(f"Error generating Chinese title: {str(e)}")
        return "无标题"  # Return "No title" in Chinese if generation fails

if __name__ == '__main__':
    main() 