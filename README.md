# VoiceConnect

A multi-tenant platform that gives any business an AI phone number. When someone calls, an AI agent answers, holds a real conversation, collects caller details, and sends a follow-up email.

## What it does

A business signs up and gets their own dedicated phone number. When a caller dials that number, the AI answers, identifies what the caller wants, collects the relevant details, and saves the interaction for the client team. If the caller confirms they want a follow-up, the system sends an email summary.

Admins manage clients, provisioning, usage, and billing manually from a single dashboard. Clients log in to see their own callers, call logs, and agent settings.

## Tech stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python), deployed on Google Cloud Run |
| Database | Google Cloud Firestore |
| Phone | Twilio (inbound telephony + number provisioning) |
| Voice AI | Agentic conversational AI (per-client agents with client-specific knowledge bases) |
| Frontend | React 18 + Vite + Tailwind CSS, deployed on Google Cloud Run |
| Auth | JWT (HS256) + bcrypt, Google OAuth for per-client Gmail integration |
| Email | Gmail API (OAuth) or Gmail SMTP app password |

## Architecture overview

```
Caller → Twilio number
           ↓ TwiML routes to voice AI agent (GET /twilio/voice/{client_id})
        Agentic AI ←→ Client knowledge base (scraped from their website)
           ↓ POST /elevenlabs/initiate  (pre-call: inject caller profile)
           ↓ POST /elevenlabs/post-call (after call: save profile + trigger follow-up)
          Firestore (caller profiles, call logs, client records)
            ↓
          Gmail → Caller
```

**Multi-tenancy:** Each client gets their own Firestore sub-collection (`clients/{client_id}/caller_profiles`), their own AI agent, and their own knowledge base.

**Returning callers:** On each call, the `/elevenlabs/initiate` endpoint looks up the caller's existing profile and injects it as dynamic variables into the agent, so the AI already knows who they are.

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check + Firestore status |
| `POST` | `/elevenlabs/initiate` | Pre-call hook: returns caller profile as dynamic variables |
| `POST` | `/elevenlabs/post-call` | Post-call webhook: saves profile + sends follow-up |
| `GET` | `/twilio/voice/{client_id}` | Returns TwiML routing the call to the client's agent |
| `POST` | `/auth/login` | Admin or client login → JWT |
| `POST` | `/auth/signup` | Client self-serve signup (creates pending account) |
| `GET` | `/auth/gmail/connect-url` | Returns Google OAuth URL to connect client's Gmail |
| `GET` | `/auth/gmail/callback` | OAuth callback; stores refresh token in Firestore |
| `GET` | `/api/clients` | Admin: list all clients |
| `POST` | `/api/clients` | Admin: create client (provisions KB + agent + phone number) |
| `POST` | `/api/clients/{id}/provision` | Admin: provision a pending client |
| `DELETE` | `/api/clients/{id}` | Admin: delete client + release resources |
| `GET` | `/api/callers` | Admin: list callers across all clients |
| `GET` | `/api/callers/{phone}` | Admin: get caller detail |
| `GET` | `/api/settings` | Admin: read platform-wide caller labels |
| `POST` | `/api/settings` | Admin: update platform-wide caller labels |
| `GET` | `/api/failed-notifications` | Admin: list failed follow-up attempts |
| `GET` | `/me/profile` | Client: their own profile |
| `GET` | `/me/callers` | Client: their own callers |
| `GET` | `/me/callers/{phone}` | Client: caller detail |
| `GET` | `/me/settings` | Client: their call handling and caller labels |
| `POST` | `/me/settings` | Client: save call handling settings |

## Local setup

### Prerequisites

- Python 3.12
- Node.js 18+
- A Google Cloud project with Firestore enabled
- Twilio account
- Agentic voice AI platform credentials (agent ID + API key)

### Backend

```bash
cd ghost-phone

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

Create a `.env` file:

```bash
# AI agent
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=          # template agent to clone for new clients

# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=

# Follow-up
FOLLOW_UP_URL=                 # link sent to callers (e.g. resume upload page)
FOLLOW_UP_COMPANY_NAME=VoiceConnect

# Gmail (platform-level fallback sender)
GMAIL_SENDER_EMAIL=
GMAIL_APP_PASSWORD=

# Google OAuth (for per-client Gmail connect)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=

# Auth
JWT_SECRET_KEY=                # long random string
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=

# CORS
CORS_ORIGINS=http://localhost:5173
```

Start the server:

```bash
uvicorn app.main:app --reload --port 8000
```

For local Twilio webhook testing, expose the server:

```bash
ngrok http 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:5173` and expects the backend at `http://localhost:8000`.

## Deployment (Google Cloud Run)

### Backend

```bash
gcloud config set project YOUR_PROJECT_ID

gcloud run deploy voiceconnect-api \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

Set all environment variables via the Cloud Run console or `--set-env-vars`.

### Frontend

```bash
cd frontend
npm run build

gcloud run deploy voiceconnect-frontend \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

### After deploying

Point each provisioned Twilio number's voice webhook at:
```
https://your-api-url.run.app/twilio/voice/{client_id}
```

This is done automatically during client provisioning if the backend URL is correct.

## Client provisioning flow

1. Client signs up at `/signup` → account created in Firestore with status `pending`
2. Admin clicks **Provision** in the dashboard
3. Backend automatically:
   - Creates a knowledge base from the client's website URL
   - Clones the template agent with that knowledge base
   - Buys a Twilio phone number in the client's preferred area code
   - Wires the Twilio webhook to `/twilio/voice/{client_id}`
4. Status becomes `active` — client is live

If provisioning fails (e.g. no number available in that area code), the error is stored and admin can retry.

## Caller profile structure

Profiles in Firestore are namespaced per client and keyed by E.164 phone number:

```json
{
  "last_intent": "JOB_SEEKER",
  "last_interaction": "2026-04-17T10:00:00Z",
  "created_at": "2026-04-01T09:00:00Z",
  "intents": {
    "JOB_SEEKER": {
      "name": "Jane Smith",
      "email_address": "jane@example.com",
      "role_interest": "Software Engineer",
      "experience_years": "5",
      "contact_preference": "email",
      "transcript_summary": "..."
    },
    "GENERAL_INQUIRY": { ... }
  }
}
```

Each intent is stored separately so a returning caller who called about a job once and a general inquiry another time has both records preserved.

## Billing

Usage is tracked per client in the admin dashboard. Billing is handled manually by admin; there is no in-app paywall or self-serve checkout flow.

## Follow-up logic

After each call, the system checks the caller's `contact_preference`:

- **`email`** — sends via the client's connected Gmail (OAuth) if available, otherwise falls back to the platform Gmail SMTP account
- **`whatsapp`** — sends via Twilio WhatsApp from the client's purchased number
- **anything else / missing** — logs a failed notification to Firestore

Failed follow-ups are visible on the admin **Failed Notifications** page with the exact reason.

## Environment variables reference

| Variable | Description | Required |
|---|---|---|
| `ELEVENLABS_API_KEY` | Voice AI platform API key | Yes |
| `ELEVENLABS_AGENT_ID` | Template agent ID to clone per client | Yes |
| `TWILIO_ACCOUNT_SID` | Twilio account SID | Yes |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | Yes |
| `TWILIO_WHATSAPP_FROM` | Default WhatsApp sender (sandbox or approved number) | Yes |
| `FOLLOW_UP_URL` | Link included in follow-up messages | Yes |
| `FOLLOW_UP_COMPANY_NAME` | Company name in follow-up messages | No |
| `GMAIL_SENDER_EMAIL` | Platform-level fallback sender email | No |
| `GMAIL_APP_PASSWORD` | App password for platform Gmail | No |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (for per-client Gmail) | No |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret | No |
| `GOOGLE_REDIRECT_URI` | OAuth redirect URI | No |
| `JWT_SECRET_KEY` | Secret for signing JWTs | Yes |
| `DASHBOARD_USERNAME` | Admin login username | Yes |
| `DASHBOARD_PASSWORD` | Admin login password | Yes |
| `JWT_EXPIRE_MINUTES` | Token lifetime in minutes (default: 1440) | No |
| `CORS_ORIGINS` | Comma-separated allowed origins | Yes |

## Project structure

```
ghost-phone/
├── app/
│   ├── main.py                  # FastAPI app, webhook handlers, call routing
│   ├── auth.py                  # JWT auth, login/signup, Gmail OAuth
│   ├── dashboard.py             # Admin + client API routes
│   ├── notifications.py         # WhatsApp + email follow-up sending
│   ├── config.py                # Settings (pydantic-settings)
│   ├── schemas.py               # Pydantic models for webhooks
│   └── services/
│       └── profile_services.py  # Firestore read/write for caller profiles
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # React router
│   │   ├── api.js               # API client
│   │   ├── pages/
│   │   │   ├── Login.jsx
│   │   │   ├── admin/           # Clients, Callers, Settings, FailedNotifications
│   │   │   └── client/          # Callers, Settings
│   │   └── components/
│   │       ├── Layout.jsx
│   │       └── CallerSlideOver.jsx
│   ├── package.json
│   └── vite.config.js
├── requirements.txt
├── USER_MANUAL.md               # Admin operations guide
└── README.md
```

## License

Proprietary — Bhuvi IT Solutions
