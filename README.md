# SEA News Processing and Delivery System

This repository contains scripts for collecting and delivering SEA news articles via email.

## Security Setup

### Required Secrets

The following secrets need to be set up in GitHub Actions:

1. `OPENAI_API_KEY`: Your OpenAI API key
2. `GOOGLE_APPLICATION_CREDENTIALS`: Base64 encoded Firebase service account key
3. `SMTP_USERNAME`: SMTP2Go username
4. `SMTP_PASSWORD`: SMTP2Go password
5. `EMAIL_FROM`: Sender email address
6. `EMAIL_RECIPIENTS`: Comma-separated list of recipient email addresses

### Local Setup

1. Create a `.env` file with the following structure:
```env
OPENAI_API_KEY=your_openai_api_key
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
EMAIL_FROM=your_email@domain.com
EMAIL_RECIPIENTS=recipient1@domain.com,recipient2@domain.com
```

2. Place your Firebase service account key file in the root directory:
   - File name should match the pattern: `*-firebase-adminsdk-*.json`
   - This file is automatically ignored by `.gitignore`

## GitHub Actions Setup

1. Go to your repository settings
2. Navigate to "Secrets and variables" → "Actions"
3. Add each required secret as listed above
4. For the Firebase credentials:
   - Convert your service account key file to base64
   - Add it as the `GOOGLE_APPLICATION_CREDENTIALS` secret

## Schedule

The workflow runs automatically at:
- News collection: 10:00 PM UTC+4 (18:00 UTC)
- Email delivery: 11:55 PM UTC+4 (19:55 UTC)

You can also trigger the workflow manually from the Actions tab.

## Development

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the scripts:
```bash
python get_today_news.py
python news_delivery.py
``` 