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
            time.sleep(2 ** attempt)

@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def safe_batch_commit(batch):
    """Safely commit a batch with exponential backoff"""
    batch.commit()

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

def get_today_news():
    try:
        # Get today's date in UTC+4 timezone
        dubai_tz = pytz.timezone('Asia/Dubai')
        today_str = datetime.now(dubai_tz).strftime("%Y-%m-%d")
        logger.info(f"Looking for articles with date (UTC+4): {today_str}")
        
        # Delete old data first
        delete_old_data()
        
        # Get all documents from the articles collection
        articles_ref = db.collection('articles')
        docs = safe_get_documents(articles_ref)
        
        if not docs:
            logger.warning("No documents found in articles collection")
            return
        
        # Prepare for processing
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
                
                if processed_count % 100 == 0:
                    logger.info(f"Processed {processed_count} articles...")
                
                if not article_date:
                    logger.warning(f"Skipping article {doc.id} - no date found")
                    continue
                
                if str(article_date).startswith(today_str):
                    matched_count += 1
                    logger.info(f"Found matching article {matched_count}: {doc.id} with date {article_date}")
                    
                    if not all(key in data for key in ['title', 'date', 'content', 'source']):
                        logger.warning(f"Skipping article {doc.id} due to missing required fields")
                        continue
                    
                    cleaned_source = clean_source_name(data['source'])
                    source_counts[cleaned_source] = source_counts.get(cleaned_source, 0) + 1
                    
                    # Generate summaries with retry logic
                    max_summary_attempts = 3
                    summaries = None
                    for attempt in range(max_summary_attempts):
                        try:
                            summaries = generate_summaries(data['content'])
                            if summaries['English_summary'] and summaries['Chinese_summary']:
                                break
                        except Exception as e:
                            if attempt == max_summary_attempts - 1:
                                logger.error(f"Failed to generate summaries for {doc.id} after {max_summary_attempts} attempts")
                                continue
                            logger.warning(f"Summary generation attempt {attempt + 1} failed, retrying...")
                            time.sleep(5)  # Wait 5 seconds before retry
                    
                    if not summaries or not summaries['English_summary'] or not summaries['Chinese_summary']:
                        logger.error(f"Skipping article {doc.id} - failed to generate summaries")
                        continue
                    
                    article_data = {
                        'article_info': {
                            'title': data['title'],
                            'date': data['date'],
                            'content': data['content'],
                            'source': cleaned_source,
                            'original_source': data['source'],
                            'original_doc_id': doc.id
                        },
                        'processing_info': {
                            'processed_at': datetime.now(dubai_tz).strftime("%Y-%m-%d %H:%M:%S"),
                            'timezone': 'UTC+4',
                            'target_date': today_str,
                            'status': 'processed'
                        },
                        'metadata': {
                            'word_count': len(data['content'].split()),
                            'has_image': 'image_url' in data,
                            'source_type': data.get('source_type', 'unknown'),
                            'article_number': source_counts[cleaned_source]
                        },
                        'English_summary': summaries['English_summary'],
                        'Chinese_summary': summaries['Chinese_summary']
                    }
                    
                    # Write each document immediately with retry logic
                    max_write_attempts = 3
                    for attempt in range(max_write_attempts):
                        try:
                            timestamp = int(time.time() * 1000)
                            doc_id = f"{today_str}_{cleaned_source}_{timestamp}_{source_counts[cleaned_source]}"
                            doc_ref = today_news_ref.document(doc_id)
                            doc_ref.set(article_data)
                            saved_count += 1
                            logger.info(f"Saved article {doc_id} ({saved_count} articles saved)")
                            break
                        except Exception as e:
                            if attempt == max_write_attempts - 1:
                                logger.error(f"Failed to save article {doc.id} after {max_write_attempts} attempts: {str(e)}")
                                continue
                            logger.warning(f"Save attempt {attempt + 1} failed, retrying in 5 seconds...")
                            time.sleep(5)
                    
                    # Wait 5 seconds before processing next article
                    logger.info("Waiting 5 seconds before processing next article...")
                    time.sleep(5)
                    
            except Exception as e:
                logger.error(f"Error processing article {doc.id}: {str(e)}")
                continue
        
        logger.info(f"Total articles processed: {processed_count}")
        logger.info(f"Articles matching date {today_str}: {matched_count}")
        logger.info(f"Articles successfully saved: {saved_count}")
        
        # Final count check
        count_today_news()
        
    except Exception as e:
        logger.error(f"An error occurred in get_today_news: {str(e)}")
        raise

def generate_summaries(content):
    """Generate English and Chinese summaries directly from content using OpenAI API"""
    try:
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
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
        
        # 2. Wait for 5 seconds before generating Chinese summary
        logger.info("Waiting 5 seconds before generating Chinese summary...")
        time.sleep(5)
        
        # 3. Generate Chinese summary with strict requirements for Chinese output
        chinese_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": """你是一个专业的中文新闻摘要助手。你必须用中文回答，不允许输出任何英文。

要求：
1. 必须用中文生成2-3个完整的句子
2. 每个句子必须是正确的中文语法，包含完整的主谓宾结构
3. 每个句子必须以中文句号"。"结尾
4. 使用正式的中文新闻报道语言
5. 确保摘要完整表达文章的主要内容
6. 严禁输出任何英文内容"""
                },
                {
                    "role": "user", 
                    "content": f"""请严格按照以下要求生成中文新闻摘要：

1. 第一句：用中文描述主要事件或核心信息，以句号结尾。
2. 第二句：用中文补充重要细节或影响，以句号结尾。
3. 如果需要第三句：用中文补充额外重要信息，以句号结尾。
4. 只输出中文，不要输出任何英文。

新闻内容：
{content}"""
                }
            ],
            max_tokens=500,
            temperature=0.7,
            presence_penalty=0.1,
            frequency_penalty=0.1
        )
        chinese_summary = chinese_response.choices[0].message.content.strip()
        
        # Verify Chinese summary completeness and language
        def is_complete_chinese_summary(text):
            # Check if summary has at least 2 complete sentences ending with Chinese period
            sentences = [s.strip() for s in text.split('。') if s.strip()]
            if len(sentences) < 2:
                return False
            # Check if last character is a Chinese period
            if not text.endswith('。'):
                return False
            # Check minimum length
            if len(text) < 50:
                return False
            # Check if text contains Chinese characters
            if not any('\u4e00' <= char <= '\u9fff' for char in text):
                return False
            return True
        
        # If summary is not proper Chinese, retry with stronger Chinese requirement
        if not is_complete_chinese_summary(chinese_summary):
            logger.warning("Initial Chinese summary was incomplete or not in Chinese, retrying...")
            time.sleep(5)  # Wait 5 seconds before retry
            chinese_response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": """你必须用纯中文回答！不允许输出任何英文！
1. 只能输出中文
2. 必须生成至少两个完整的中文句子
3. 每个中文句子都必须以"。"结尾
4. 使用正式的中文新闻语言
5. 禁止输出任何英文内容"""
                    },
                    {
                        "role": "user",
                        "content": f"请用纯中文总结这篇新闻（至少两句话，必须是中文，必须以中文句号结尾）：\n\n{content}"
                    }
                ],
                max_tokens=500,
                temperature=0.7
            )
            chinese_summary = chinese_response.choices[0].message.content.strip()
            
            # Ensure it ends with a Chinese period
            if not chinese_summary.endswith('。'):
                chinese_summary += '。'
        
        # 4. Wait 5 seconds before next operation
        logger.info("Waiting 5 seconds before next operation...")
        time.sleep(5)
        
        # Log summaries for verification
        logger.info("Generated English summary: " + english_summary)
        logger.info("Generated Chinese summary: " + chinese_summary)
        
        # Final verification - if still not Chinese, raise an error
        if not any('\u4e00' <= char <= '\u9fff' for char in chinese_summary):
            raise ValueError("Failed to generate Chinese summary - output does not contain Chinese characters")
        
        return {
            "English_summary": english_summary,
            "Chinese_summary": chinese_summary
        }
    except Exception as e:
        logger.error(f"Error generating summaries: {str(e)}")
        return {
            "English_summary": "",
            "Chinese_summary": ""
        }

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
                    'English_summary': english_summary,
                    'Chinese_summary': chinese_summary
                })
                
                processed_count += 1
                logger.info(f"Processed document {doc.id} ({processed_count} documents processed)")
                
                # 4. Wait 3 seconds before next document
                logger.info("Waiting 3 seconds before next document...")
                time.sleep(3)
                
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
    get_today_news()
    # If you want to generate summaries for existing documents
    # generate_summaries_for_today_news()
    # If you want to just check the current count without processing new articles
    # count_today_news() 