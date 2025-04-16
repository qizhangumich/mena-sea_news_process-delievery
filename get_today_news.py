import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import pytz
import logging
import time
from openai import OpenAI
import os
from dotenv import load_dotenv
from google.api_core import retry
from google.cloud.firestore_v1.base_query import BaseQuery
import backoff
import sys

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firebase once at the module level
try:
    cred = credentials.Certificate(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    logger.error(f"Failed to initialize Firebase: {str(e)}")
    raise

def safe_get_documents(collection_ref, max_attempts=3):
    """Safely get documents from a collection with retry logic"""
    attempt = 0
    while attempt < max_attempts:
        try:
            return list(collection_ref.stream())
        except Exception as e:
            attempt += 1
            if attempt == max_attempts:
                logger.error(f"Failed to get documents after {max_attempts} attempts: {str(e)}")
                raise
            logger.warning(f"Attempt {attempt} failed, retrying in {2 ** attempt} seconds...")
            time.sleep(3 ** attempt)

@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def safe_batch_commit(batch):
    """Safely commit a batch with exponential backoff"""
    batch.commit()

def generate_chinese_title(title):
    """Translate the title to Chinese using OpenAI"""
    try:
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a professional translator. Translate the title to Chinese accurately and concisely."},
                {"role": "user", "content": f"Translate this title to Chinese: {title}"}
            ],
            max_tokens=100,
            temperature=0.7
        )
        chinese_title = response.choices[0].message.content.strip()
        return chinese_title
    except Exception as e:
        logger.error(f"Error generating Chinese title: {str(e)}")
        return ""

def clean_source_name(source):
    """Remove 'Crawler' from source name if present"""
    if source.endswith('Crawler'):
        return source[:-7]  # Remove last 7 characters ('Crawler')
    return source

def count_today_news():
    """Count total records in today_news collection"""
    try:
        today_news_ref = db.collection('today_news')
        docs = today_news_ref.stream()
        
        # Count documents and organize by source
        total_count = 0
        source_counts = {}
        
        for doc in docs:
            total_count += 1
            data = doc.to_dict()
            source = data.get('article_info', {}).get('source', 'unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
        
        # Print results
        logger.info("\n=== Today News Collection Statistics ===")
        logger.info(f"Total records: {total_count}")
        logger.info("\nBreakdown by source:")
        for source, count in sorted(source_counts.items()):
            logger.info(f"{source}: {count} articles")
        logger.info("=====================================")
        
        return total_count
            
    except Exception as e:
        logger.error(f"Error counting today_news records: {str(e)}")
        raise

def delete_old_data():
    """Delete all documents from today_news collection"""
    try:
        today_news_ref = db.collection('today_news')
        docs = today_news_ref.stream()
        
        # Create a batch for deletion
        batch = db.batch()
        count = 0
        
        # Add all documents to the batch for deletion
        for doc in docs:
            batch.delete(doc.reference)
            count += 1
        
        # Commit the batch deletion
        if count > 0:
            batch.commit()
            logger.info(f"Deleted {count} old documents from today_news collection")
        else:
            logger.info("No old documents to delete")
            
    except Exception as e:
        logger.error(f"Error deleting old data: {str(e)}")
        raise

def generate_summaries(content):
    """Generate English and Chinese summaries using OpenAI"""
    try:
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        # Generate English summary
        english_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Create a concise 2-3 sentence summary of the news article."},
                {"role": "user", "content": f"Summarize this news article:\n\n{content}"}
            ],
            max_tokens=300,
            temperature=0.7
        )
        english_summary = english_response.choices[0].message.content.strip()
        
        # Wait 5 seconds before making next API call
        time.sleep(5)
        
        # Generate Chinese summary
        chinese_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "用3-5句话总结新闻文章的主要内容。请使用正式的中文新闻语言，确保summary是以句号结尾。"},
                {"role": "user", "content": f"请用中文总结这篇新闻：\n\n{content}"}
            ],
            max_tokens=300,
            temperature=0.7
        )
        chinese_summary = chinese_response.choices[0].message.content.strip()
        
        return {
            "english_summary": english_summary,
            "chinese_summary": chinese_summary
        }
    except Exception as e:
        logger.error(f"Error generating summaries: {str(e)}")
        return {
            "english_summary": "",
            "chinese_summary": ""
        }

def get_today_news(target_date=None):
    try:
        # Get target date or today's date in UTC+4 timezone
        dubai_tz = pytz.timezone('Asia/Dubai')
        if target_date:
            today_str = target_date
        else:
            today_str = datetime.now(dubai_tz).strftime("%Y-%m-%d")
        logger.info(f"Looking for articles with date: {today_str}")
        
        # Delete old data first
        delete_old_data()
        
        # Get all documents from the articles collection with retry
        articles_ref = db.collection('articles')
        try:
            docs = list(articles_ref.stream())  # Convert to list to avoid streaming timeout
        except Exception as e:
            logger.error(f"Error fetching articles: {e}")
            return
        
        if not docs:
            logger.warning("No documents found in articles collection")
            return
        
        logger.info(f"Found {len(docs)} total articles to process")
        
        # Process articles
        processed_count = 0
        matched_count = 0
        saved_count = 0
        source_counts = {}
        today_news_ref = db.collection('today_news')
        
        for doc in docs:
            try:
                processed_count += 1
                data = doc.to_dict()
                article_date = data.get('date')
                
                if not article_date:
                    continue
                
                if str(article_date).startswith(today_str):
                    matched_count += 1
                    logger.info(f"Found matching article {matched_count}: {doc.id}")
                    
                    if not all(key in data for key in ['title', 'date', 'content', 'source']):
                        continue
                    
                    cleaned_source = clean_source_name(data['source'])
                    source_counts[cleaned_source] = source_counts.get(cleaned_source, 0) + 1
                    
                    # Generate Chinese title and summaries
                    chinese_title = generate_chinese_title(data['title'])
                    summaries = generate_summaries(data['content'])
                    
                    article_data = {
                        'article_info': {
                            'title': data['title'],
                            'chinese_title': chinese_title,
                            'date': data['date'],
                            'content': data['content'],
                            'source': cleaned_source,
                            'original_source': data['source'],
                            'original_doc_id': doc.id
                        },
                        'english_summary': summaries['english_summary'],
                        'chinese_summary': summaries['chinese_summary']
                    }
                    
                    # Save to today_news collection with retry
                    timestamp = int(time.time() * 1000)
                    doc_id = f"{today_str}_{cleaned_source}_{timestamp}_{source_counts[cleaned_source]}"
                    doc_ref = today_news_ref.document(doc_id)
                    
                    max_retries = 3
                    for retry in range(max_retries):
                        try:
                            doc_ref.set(article_data)
                            saved_count += 1
                            logger.info(f"Successfully saved article {doc_id}")
                            break
                        except Exception as e:
                            if retry == max_retries - 1:
                                logger.error(f"Failed to save article {doc_id} after {max_retries} attempts: {e}")
                            else:
                                logger.warning(f"Retry {retry + 1} for saving article {doc_id}")
                                time.sleep(2)
                    
                    # Wait 5 seconds before processing next article
                    time.sleep(5)
            
            except Exception as e:
                logger.error(f"Error processing article {doc.id}: {str(e)}")
                continue
        
        logger.info(f"Total articles processed: {processed_count}")
        logger.info(f"Articles matching date {today_str}: {matched_count}")
        logger.info(f"Articles successfully saved: {saved_count}")
        
    except Exception as e:
        logger.error(f"An error occurred in get_today_news: {str(e)}")
        raise

def generate_summaries_for_today_news():
    """Generate English and Chinese summaries for existing today_news documents"""
    try:
        # Get all documents from today_news collection
        today_news_ref = db.collection('today_news')
        docs = today_news_ref.stream()
        
        # Initialize OpenAI client
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        processed_count = 0
        for doc in docs:
            try:
                data = doc.to_dict()
                content = data.get('article_info', {}).get('content')
                
                if not content:
                    logger.warning(f"Skipping document {doc.id} - no content found")
                    continue
                
                # 1. Generate English summary
                english_response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that creates concise news summaries."},
                        {"role": "user", "content": f"Please provide a concise summary (around 2-3 sentences) of the following news article:\n\n{content}"}
                    ],
                    max_tokens=150,
                    temperature=0.7
                )
                english_summary = english_response.choices[0].message.content.strip()
                
                # 2. Wait for 3 seconds before generating Chinese summary
                logger.info("Waiting 3 seconds before generating Chinese summary...")
                time.sleep(3)
                
                # 3. Generate Chinese summary directly from content
                chinese_response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that creates concise news summaries in Chinese."},
                        {"role": "user", "content": f"请用中文简要总结以下新闻文章（2-3句话）：\n\n{content}"}
                    ],
                    max_tokens=150,
                    temperature=0.7
                )
                chinese_summary = chinese_response.choices[0].message.content.strip()
                
                # Update the document with both summaries
                doc.reference.update({
                    'english_summary': english_summary,
                    'chinese_summary': chinese_summary
                })
                
                processed_count += 1
                logger.info(f"Processed document {doc.id} ({processed_count} documents processed)")
                
                # 4. Wait 3 seconds before next document
                logger.info("Waiting 5 seconds before next document...")
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"Error processing document {doc.id}: {str(e)}")
                continue
        
        logger.info(f"Successfully processed {processed_count} documents")
        
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        raise

def ensure_today_news_collection():
    """Ensure today_news collection exists, create it if it doesn't"""
    try:
        # Try to access the collection
        today_news_ref = db.collection('today_news')
        
        # Create a dummy document to ensure collection exists
        dummy_doc = today_news_ref.document('initialization')
        dummy_doc.set({
            'initialization_time': datetime.now(pytz.timezone('Asia/Dubai')).strftime("%Y-%m-%d %H:%M:%S"),
            'status': 'collection_created'
        })
        
        # Delete the dummy document
        dummy_doc.delete()
        
        logger.info("Ensured today_news collection exists")
        
    except Exception as e:
        logger.error(f"Error ensuring today_news collection: {str(e)}")
        raise

if __name__ == "__main__":
    # First ensure the today_news collection exists
    ensure_today_news_collection()
    # Then get today's news and generate summaries
    # Get target date from command line argument if provided
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
        logger.info(f"Using provided target date: {target_date}")
    else:
        # Use today's date by default
        dubai_tz = pytz.timezone('Asia/Dubai')
        target_date = datetime.now(dubai_tz).strftime("%Y-%m-%d")
        logger.info(f"Using today's date: {target_date}")
    
    get_today_news(target_date)
    # If you want to generate summaries for existing documents
    # generate_summaries_for_today_news()
    # If you want to just check the current count without processing new articles
    # count_today_news() 