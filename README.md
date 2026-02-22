# VoiceConnect - AI-Powered Voice Receptionist

An intelligent voice receptionist for Bhuvi IT Solutions that handles incoming phone calls, classifies user intent, extracts information, and routes calls appropriately.

## 🎯 Features

- **Intelligent Call Classification**: Automatically identifies Job Seekers, Client Leads, and General Inquiries
- **Real-Time Job Integration**: Fetches current job openings from BhuviIT website
- **Conversation Memory**: Tracks conversation history to avoid repeating questions
- **Multi-Language Support**: Supports English, Spanish, and Hindi (with language tags)
- **RAG-Powered Responses**: Uses ChromaDB + Sentence Transformers for context-aware answers
- **Speech-to-Text**: Deepgram integration for accurate transcription
- **AI-Powered Dialogue**: Claude (Anthropic) for intelligent responses
- **Automated Job Updates**: Web scraper to keep job listings fresh

## 📋 Prerequisites

- Python 3.12
- Google Cloud account (for deployment)
- Twilio account (for phone integration)
- API Keys:
  - Anthropic API Key
  - Deepgram API Key

## 🚀 Local Setup

### 1. Clone & Install

```bash
git clone <your-repo-url>
cd ghost-phone

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file:

```bash
ANTHROPIC_API_KEY=your_anthropic_api_key_here
DEEPGRAM_API_KEY=your_deepgram_api_key_here
```

### 3. Initialize Knowledge Base

```bash
# Generate vector database from knowledge base
python3 ingest.py
```

You should see: `✅ Successfully stored X facts in the Vector Database!`

### 4. Run Locally

```bash
# Start the server
uvicorn app.main:app --reload --port 8000

# In another terminal, expose with ngrok (for Twilio testing)
ngrok http 8000
```

### 5. Test the API

```bash
# Test health endpoint
curl http://localhost:8000/

# Test AI response
curl -X POST http://localhost:8000/process-speech \
  -H "Content-Type: application/json" \
  -d '{"text": "Hi, I am looking for a job", "language": "en"}'
```

## ☁️ Google Cloud Deployment

### Automated Deployment

This project uses Docker and deploys to Google Cloud Run.

### Deploy Steps

1. **Build & Deploy**:

```bash
# Set your project ID
gcloud config set project YOUR_PROJECT_ID

# Build and deploy
gcloud run deploy voice-connect \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars ANTHROPIC_API_KEY=your_key,DEEPGRAM_API_KEY=your_key
```

2. **Post-Deployment Setup**:

The Dockerfile automatically runs `ingest.py` during container build, so the vector database is ready on deployment.

3. **Configure Twilio**:

- Go to your Twilio Console
- Navigate to your phone number settings
- Set **Voice Webhook** to: `https://your-cloud-run-url.run.app/voice`
- Set **Status Callback URL** to: `https://your-cloud-run-url.run.app/call-status`
- Set both to **HTTP POST**

## 🔄 Updating Job Listings

### Automatic Scraper

```bash
# Fetch latest jobs from website and update knowledge base
python3 jobs_scraper.py

# Re-ingest to update vector database
python3 ingest.py
```

### Schedule with Cron (Production)

```bash
# On your server, add to crontab:
0 9 * * * cd /path/to/ghost-phone && python3 jobs_scraper.py && python3 ingest.py
```

This runs daily at 9 AM to keep job listings fresh.

## 📞 Call Flow

### For Job Seekers:
1. User: "I'm looking for a job"
2. AI asks: Which role are you interested in?
3. AI asks: What's your tech stack?
4. AI asks: Years of experience?
5. AI asks: Willing to relocate/travel to US?
6. AI asks: Visa status?
7. AI: "Thank you! Let me forward you to a recruiter." → Call ends

### For Client Leads:
1. User: "We need to hire developers"
2. AI asks: What roles are you looking for?
3. AI asks: What tech stack/skills?
4. AI asks: Prefer nearshore or US-based?
5. AI: "Thank you! Let me forward you to our representative." → Call ends

### For General Inquiries:
- AI provides information from knowledge base
- Mentions TN Visas, Nearshore delivery, NearMind, etc.

## 📁 Project Structure

```
ghost-phone/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI endpoints
│   ├── config.py            # Settings
│   ├── schemas.py           # Pydantic models
│   ├── interfaces.py        # Type definitions
│   ├── data/
│   │   └── knowledge_base.txt   # Company & job information
│   └── services/
│       ├── llm_service.py   # Claude AI integration
│       └── stt_service.py   # Deepgram speech-to-text
├── chroma_db/               # Vector database (generated, not in git)
├── ingest.py                # Knowledge base ingestion script
├── jobs_scraper.py          # Automated job listing scraper
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container configuration
└── README.md                # This file
```

## 🧪 Testing

### Test Endpoints

```bash
# Process speech endpoint
curl -X POST http://localhost:8000/process-speech \
  -H "Content-Type: application/json" \
  -d '{"text": "What job positions do you have?", "language": "en"}'

# Voice webhook (Twilio entry point)
curl -X POST http://localhost:8000/voice \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=TEST123"
```

### Test Call Scenarios

1. **Job Seeker**: Call and say "I'm looking for a software engineer job"
2. **Client**: Call and say "We need to hire AI developers"
3. **General**: Call and say "Do you handle TN visas?"
4. **Forward**: Ask "Can I speak to someone?" to trigger forwarding

## 🛠️ Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | Claude API key for AI responses | Yes |
| `DEEPGRAM_API_KEY` | Deepgram API key for speech-to-text | Yes |
| `MODEL_NAME` | Claude model (default: claude-3-haiku-20240307) | No |

### Timeouts

- Recording timeout: **3 seconds** of silence
- Max recording length: **30 seconds**
- Initial greeting length: **10 seconds**

### Knowledge Base

Edit `app/data/knowledge_base.txt` to update:
- Company information
- Services offered
- Job listings (or use the scraper)

After editing, run: `python3 ingest.py`

## 📊 Monitoring

### Logs

View logs in Google Cloud Console or locally:

```bash
# Local logs show:
[NEW CALL] CallSid: CAxxxx
[CAxxxx] User said: I'm looking for a job
[CAxxxx] AI response: [EN] Great! Which role are you interested in?
[CAxxxx] Conversation history length: 1
```

### Common Issues

**Issue**: AI not mentioning jobs  
**Solution**: Run `python3 ingest.py` to regenerate vector database

**Issue**: Call ends immediately  
**Solution**: Check Twilio webhook URLs are correct

**Issue**: "ERROR" response from AI  
**Solution**: Check API keys in `.env` and server logs

## 🔐 Security

- ⚠️ **Never commit `.env`** - it contains sensitive API keys
- ⚠️ **Don't commit `chroma_db/`** - regenerate on deployment
- ✅ Use environment variables in Google Cloud Run
- ✅ Regularly rotate API keys

## 📝 License

Proprietary - Bhuvi IT Solutions

## 👥 Support

For issues or questions, contact the Bhuvi IT development team.

---

Built with ❤️ for Bhuvi IT Solutions
