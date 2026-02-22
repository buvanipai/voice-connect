# Job Integration Guide

## Overview
The Voice Receptionist now integrates with BhuviIT's job listings from https://bhuviits.com/category/jobs/ to provide candidates with real-time information about open positions.

## How It Works

### 1. **Job Data in Knowledge Base**
Job listings are stored in `app/data/knowledge_base.txt` and indexed in ChromaDB for RAG-based retrieval.

### 2. **Enhanced Candidate Flow**  
When a candidate calls about jobs, the AI will now ask:
1. **Which specific role** are you interested in? (References actual job openings)
2. **What is your tech stack?** (e.g., Python, React, AWS, Java)
3. **How many years of experience** do you have?
4. **Are you willing to relocate or travel** to the US?
5. **What is your visa status?** (US Citizen, Green Card, need sponsorship)

Once all information is collected OR the caller asks for a human, the call is forwarded to Subbu.

### 3. **Client Flow** 
For clients/companies calling to hire:
1. What roles are they looking to hire for?
2. What specific skills or tech stack?
3. Do they prefer nearshore talent or US-based?

## Keeping Jobs Up-to-Date

### Option 1: Automatic Scraper (Recommended)
Run the job scraper to automatically fetch the latest jobs from the website:

```bash
# Fetch latest jobs and update knowledge base
python3 jobs_scraper.py

# Re-ingest into vector database
python3 ingest.py
```

**Schedule it with cron (Unix/Mac):**
```bash
# Edit crontab
crontab -e

# Add this line to run daily at 9 AM
0 9 * * * cd /path/to/ghost-phone && python3 jobs_scraper.py && python3 ingest.py
```

### Option 2: Manual Updates
1. Edit `app/data/knowledge_base.txt` and add/update job listings
2. Run `python3 ingest.py` to update the vector database

## Testing the Enhanced System

### Test the API locally:
```bash
# Start the server
uvicorn app.main:app --reload

# In another terminal, test with a candidate query:
curl -X POST http://localhost:8000/process-speech \
  -H "Content-Type: application/json" \
  -d '{"text": "Hi, I am looking for a job", "language": "en"}'
```

Expected response should mention specific job openings like "Software Engineer" or "UX Designer".

### Test with Twilio (Phone):
1. Make sure your Twilio webhook points to your server: `https://your-domain.com/voice`
2. Call your Twilio number
3. Say: "I'm looking for a job"
4. The AI should ask you which specific role you're interested in

## Job Scraper Details

**File:** `jobs_scraper.py`

**What it does:**
- Fetches jobs from https://bhuviits.com/category/jobs/
- Parses job titles, descriptions, and posting dates
- Updates `app/data/knowledge_base.txt` with fresh job data
- Preserves the base company information (Nearshore, TN Visa, etc.)

**Dependencies:**
- `beautifulsoup4` - HTML parsing
- `requests` - HTTP requests

**Note:** If the website structure changes, you may need to update the scraper's HTML parsing logic.

## Files Modified

1. **app/data/knowledge_base.txt** - Added current job openings
2. **app/services/llm_service.py** - Enhanced prompt with job-specific questions
3. **ingest.py** - Added collection reset to avoid duplicates
4. **requirements.txt** - Added beautifulsoup4 and requests
5. **jobs_scraper.py** - New automated job scraper

## Troubleshooting

**Issue:** AI not mentioning specific jobs  
**Solution:** Make sure you ran `python3 ingest.py` after updating the knowledge base

**Issue:** Scraper not finding jobs  
**Solution:** Check if the website structure changed. Update the BeautifulSoup selectors in `jobs_scraper.py`

**Issue:** Duplicate job entries  
**Solution:** The scraper automatically removes old job sections before adding new ones

## Next Steps

Consider asking the BhuviIT team:
1. Do they have a jobs API you could use instead of scraping?
2. Where do they post jobs (WordPress admin, custom CMS, etc.)?
3. Could they provide webhooks when new jobs are posted?

An API integration would be more reliable than web scraping.
