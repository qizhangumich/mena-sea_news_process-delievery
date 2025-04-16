#!/usr/bin/env python3
import os
import logging
from datetime import datetime, timezone
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
from dotenv import load_dotenv

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
        
        # Create email content
        html_content = create_email_content(news_items)
        msg.attach(MIMEText(html_content, 'html'))
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(email_from, email_recipients, msg.as_string())
        
        logging.info(f"Email sent successfully to {len(email_recipients)} recipients")
        return True
        
    except Exception as e:
        logging.error(f"Error sending email: {str(e)}")
        return False

def create_email_content(news_items):
    """Create HTML content for the email."""
    try:
        # Generate Chinese titles for all news items
        for item in news_items:
            if 'title' in item and not item.get('chinese_title'):
                item['chinese_title'] = generate_chinese_title(item['title'])
        
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
                    <a href="{item.get('url', '#')}" class="link">Read more</a>
                </div>
                '''
                for item in news_items
            ])}
        </body>
        </html>
        """
        
        return html_content
        
    except Exception as e:
        logging.error(f"Error creating email content: {str(e)}")
        return None

if __name__ == '__main__':
    # Test title generation
    test_title = "How US tariffs could impact GCC banks and economy"
    try:
        chinese_title = generate_chinese_title(test_title)
        print(f"English title: {test_title}")
        print(f"Chinese title: {chinese_title}")
    except Exception as e:
        print(f"Error: {str(e)}") 