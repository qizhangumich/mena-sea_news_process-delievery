import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Firebase
cred = credentials.Certificate(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
firebase_admin.initialize_app(cred)
db = firestore.client()

def get_email_metrics(days=7):
    """Get email metrics for the last N days."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Get sent emails
    sent_emails = db.collection('email_sent').where('timestamp', '>=', start_date.isoformat()).stream()
    sent_data = [doc.to_dict() for doc in sent_emails]
    
    # Get opens
    opens = db.collection('email_opens').where('timestamp', '>=', start_date.isoformat()).stream()
    open_data = [doc.to_dict() for doc in opens]
    
    # Get clicks
    clicks = db.collection('email_clicks').where('timestamp', '>=', start_date.isoformat()).stream()
    click_data = [doc.to_dict() for doc in clicks]
    
    return {
        'sent': sent_data,
        'opens': open_data,
        'clicks': click_data
    }

def create_time_spent_chart(metrics):
    """Create chart for time spent reading."""
    df = pd.DataFrame(metrics['opens'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['time_spent'] = df['time_spent'].astype(float)
    
    fig = px.histogram(df, x='time_spent', 
                      title='Time Spent Reading Emails',
                      labels={'time_spent': 'Time Spent (seconds)'})
    return fig

def create_open_rate_chart(metrics):
    """Create chart for open rates."""
    sent_count = len(metrics['sent'])
    open_count = len(metrics['opens'])
    
    data = {
        'Metric': ['Sent', 'Opened'],
        'Count': [sent_count, open_count]
    }
    df = pd.DataFrame(data)
    
    fig = px.pie(df, values='Count', names='Metric',
                 title='Email Open Rate')
    return fig

def create_click_through_chart(metrics):
    """Create chart for click-through rates."""
    open_count = len(metrics['opens'])
    click_count = len(metrics['clicks'])
    
    data = {
        'Metric': ['Opened', 'Clicked'],
        'Count': [open_count, click_count]
    }
    df = pd.DataFrame(data)
    
    fig = px.pie(df, values='Count', names='Metric',
                 title='Click-Through Rate')
    return fig

def main():
    st.title('SEA News Email Analytics Dashboard')
    
    # Date range selector
    days = st.slider('Select time range (days)', 1, 30, 7)
    
    # Get metrics
    metrics = get_email_metrics(days)
    
    # Display summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Emails Sent", len(metrics['sent']))
    with col2:
        st.metric("Emails Opened", len(metrics['opens']))
    with col3:
        st.metric("Links Clicked", len(metrics['clicks']))
    
    # Display charts
    st.plotly_chart(create_open_rate_chart(metrics))
    st.plotly_chart(create_click_through_chart(metrics))
    st.plotly_chart(create_time_spent_chart(metrics))
    
    # Display raw data
    st.subheader('Raw Data')
    
    tab1, tab2, tab3 = st.tabs(['Sent', 'Opens', 'Clicks'])
    
    with tab1:
        st.dataframe(pd.DataFrame(metrics['sent']))
    
    with tab2:
        st.dataframe(pd.DataFrame(metrics['opens']))
    
    with tab3:
        st.dataframe(pd.DataFrame(metrics['clicks']))

if __name__ == "__main__":
    main() 