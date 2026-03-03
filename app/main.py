# app/main.py
import os
import datetime
import select
from dotenv import load_dotenv
from requests import get
import twilio
load_dotenv()
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
from pydoc import text
from typing import Dict, List
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, HTTPException
from app.schemas import CallPayload, AIResponse
from app.services.llm_service import LLMService
from app.services.stt_service import DeepgramSTT
from app.services.drive_service import DriveService
from app.services.profile_services import ProfileService
from app.services.metrics_service import MetricsService
from app.services.cloud_logging_service import CloudLoggingService
from twilio.rest import Client
from contextlib import asynccontextmanager
from fastapi.responses import HTMLResponse

app = FastAPI(title="VoiceConnect API", version="0.1.0")

_llm_service_instance = None
_stt_instance = None
_drive_service_instance = None
_metrics_instance = None
_cloud_logging_instance = None
# Store conversation history per call session (CallSid)
call_sessions: Dict[str, List[dict]] = {}

# Initialize Service
def get_llm_service():
    global _llm_service_instance
    if _llm_service_instance is None:
        print("[INFO] Initializing LLMService for the first time.")
        _llm_service_instance = LLMService()
    return _llm_service_instance

def get_stt_service():
    global _stt_instance
    if _stt_instance is None:
        print("[INFO] Initializing DeepgramSTT for the first time.")
        _stt_instance = DeepgramSTT()
    return _stt_instance

def get_drive_service():
    global _drive_service_instance
    if _drive_service_instance is None:
        print("[INFO] Initializing DriveService for the first time.")
        _drive_service_instance = DriveService()
    return _drive_service_instance

def get_metrics_service():
    global _metrics_instance
    if _metrics_instance is None:
        print("[INFO] Initializing MetricsService for the first time.")
        _metrics_instance = MetricsService()
    return _metrics_instance

def get_cloud_logging_service():
    global _cloud_logging_instance
    if _cloud_logging_instance is None:
        print("[INFO] Initializing CloudLoggingService for the first time.")
        _cloud_logging_instance = CloudLoggingService()
    return _cloud_logging_instance

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[INFO] Pre-loading AI models...")
    get_llm_service()
    get_stt_service()
    get_drive_service()
    print("[INFO] AI models loaded successfully.")
    yield

app = FastAPI(title="VoiceConnect API", version="0.1.0", lifespan=lifespan)

@app.get("/")
def home():
    return {"message": "Welcome to the VoiceConnect API!",
            "status": "online"}

@app.post("/process-speech", response_model=AIResponse)
async def process_speech(payload: CallPayload):
    """
    Endpoint exposed to the Telephony Service (Twilio/Rockscar).
    """
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Input text cannot be empty")
        
    service = get_llm_service()
    result = await service.analyze_call(payload.text)
    return result

# Phone endpoint for Twilio
@app.post("/voice")
async def voice_webhook(request: Request):
    """
    Step 1: Answer and ask the user to speak
    Twilio hits this endpoint when the phone rings.
    We return XML instructions telling it to speak.
    """
    # Get CallSid to track this conversation
    form_data = await request.form()
    call_sid = str(form_data.get("CallSid", "unknown"))
    caller_number = str(form_data.get("From", "unknown"))
    
    # Initialize conversation history for this call
    if call_sid not in call_sessions:
        call_sessions[call_sid] = []
        print(f"[NEW CALL] CallSid: {call_sid}")
    
    # Check if this is a returning caller
    profile_service = ProfileService()
    profile_data = profile_service.get_profile(caller_number)
    print(f"[PROFILE DEBUG] Caller: {caller_number}, Profile data: {profile_data}")
    
    # Personalized greeting for returning callers
    if profile_data and profile_data.get("last_intent") == "JOB_SEEKER":
        # Use conversational fallbacks instead of "unknown"
        role = profile_data.get('role_interest', 'an open position')
        exp = profile_data.get('experience_years', 'some')
        skills = profile_data.get('tech_stack', 'your technical skills')
        location = profile_data.get('caller_location', 'your location')
        greeting = f"Welcome back! I have your profile for the {role} role, {exp} years in {skills}, based in {location}. Is this still accurate, or do you need to update anything?"
        print(f"[RETURNING JOB_SEEKER] {caller_number}")
        print(f"[GREETING] {greeting}")
        
        # Store greeting in call memory so Claude has context for the response
        call_sessions[call_sid].append({
            "user": "[SYSTEM: Returning caller]",
            "ai": greeting,
            "intent": "JOB_SEEKER",
            "entities": profile_data
        })
    elif profile_data and profile_data.get("last_intent") == "CLIENT_LEAD":
        greeting = "Welcome back to Bhuvi IT Solutions! How can I help with your hiring needs today?"
        print(f"[RETURNING CLIENT_LEAD] {caller_number}")
        print(f"[GREETING] {greeting}")
        
        # Store greeting in call memory
        call_sessions[call_sid].append({
            "user": "[SYSTEM: Returning caller]",
            "ai": greeting,
            "intent": "CLIENT_LEAD",
            "entities": profile_data
        })
    else:
        # New caller - use generic greeting
        greeting = "Hello! Thank you for calling Bhuvi IT Solutions. Are you calling to apply for a job, looking to hire IT talent, or interested in AI development?"
        print(f"[NEW CALLER] {caller_number}")
        print(f"[GREETING] {greeting}")
    
    # Simple XML response (TwiML)
    xml_response = f"""
        <Response>
            <Say voice="Polly.Joanna-Neural">{greeting}</Say>
            <Record maxLength="10" timeout="2" trim="trim-silence" action="/transcribe" playBeep="false"/>
        </Response>
        """
    # Return as XML so Twilio understands it
    return Response(content=xml_response, media_type="application/xml")

@app.post("/transcribe")
async def transcribe_webhook(request: Request):
    """
    Step 2: Recieve recording -> Transcribe -> Echo back
    Twilio hits this endpoint after the call ends, sending the recording URL.
    We will process the recording and return a response.
    """
    form_data = await request.form()
    recording_url = str(form_data.get("RecordingUrl"))
    call_sid = str(form_data.get("CallSid", "unknown"))
    caller_country = str(form_data.get("CallerCountry", "unknown"))
    caller_state = str(form_data.get("CallerState", "unknown"))
    print(f"[{call_sid}] DEBUG: Twilio reports CallerState as: '{caller_state}'")
    caller_number = str(form_data.get("From", "unknown"))
    
    # Initialize metrics and cloud logging for this call
    metrics = get_metrics_service()
    cloud_logger = get_cloud_logging_service()
    if call_sid not in call_sessions:
        metrics.start_call(call_sid, caller_number)
        cloud_logger.log_call_event({
            "call_sid": call_sid,
            "phone_number": caller_number,
            "caller_country": caller_country,
            "caller_state": caller_state,
            "status": "started"
        })
    
    if not recording_url:
        metrics.record_stt_attempt(call_sid, success=False, text="")
        return Response(content="<Response><Say>I didn't hear anything.</Say></Response>", media_type="application/xml")
    
    # Deepgram to convert audio to text
    stt = get_stt_service()
    
    print(f"[{call_sid}] Sending URL to Deepgram: {recording_url}") # Let's verify the URL exists
    
    import time
    stt_start = time.time()
    try:
        text = await stt.transcribe(recording_url)
        stt_duration_ms = (time.time() - stt_start) * 1000
        print(f"[{call_sid}] RAW DEEPGRAM TEXT: '{text}'")
        metrics.record_stt_attempt(call_sid, success=True, text=text)
        metrics.record_latency("stt_transcribe", stt_duration_ms)
        cloud_logger.log_stt_metric(call_sid, success=True, text=text, duration_ms=stt_duration_ms)
    except Exception as e:
        stt_duration_ms = (time.time() - stt_start) * 1000
        print(f"[{call_sid}] DEEPGRAM CRASHED: {str(e)}")
        metrics.record_error(call_sid, "STT_EXCEPTION", str(e))
        metrics.record_stt_attempt(call_sid, success=False)
        metrics.record_latency("stt_transcribe", stt_duration_ms)
        cloud_logger.log_error_event(call_sid, "STT_EXCEPTION", str(e), {"duration_ms": stt_duration_ms})
        text = ""
    
    print(f"[{call_sid}] User said: {text}")
    
    if not text or not text.strip():
        print("User was silent. Asking them to repeat.")
        return Response(
            content="<Response><Say>I didn't catch that. Could you please repeat?</Say><Record maxLength='10' timeout='3' action='/transcribe' playBeep='false'/></Response>", 
            media_type="application/xml"
        )
    
    # Get conversation history for this call
    call_memory = call_sessions.get(call_sid, [])
    profile_service = ProfileService()
    profile_data = profile_service.get_profile(caller_number) or {}
    
    print(f"[{call_sid}] Processing: '{text}' (Transcription confidence may vary)")
    
    service = get_llm_service()
    llm_start = time.time()
    ai_response_obj = await service.analyze_call(
        text, 
        call_memory=call_memory, 
        caller_country=caller_country, 
        caller_state=caller_state,
        user_profile=profile_data
    )
    llm_duration_ms = (time.time() - llm_start) * 1000
    metrics.record_latency("llm_analyze", llm_duration_ms)
    
    # Track intent classification and entity extraction
    metrics.record_turn(
        call_sid, 
        text, 
        ai_response_obj.intent, 
        ai_response_obj.confidence,
        ai_response_obj.entities
    )
    
    # Log to cloud
    cloud_logger.log_turn_event(call_sid, len(call_sessions.get(call_sid, [])) + 1, {
        "user_text": text,
        "intent": ai_response_obj.intent,
        "confidence": ai_response_obj.confidence,
        "entities": ai_response_obj.entities,
        "llm_latency_ms": llm_duration_ms
    })
    
    # GUARDRAIL: Do NOT save profile data if the LLM returned an ERROR intent
    # This prevents corrupting good profile data when the system has a technical issue
    updated_data = profile_data.copy() if profile_data else {}
    
    if ai_response_obj.intent != "ERROR":
        try:
            # Prepare shared metadata (intent-agnostic)
            shared_metadata = {
                "last_intent": ai_response_obj.intent,
                "last_interaction": datetime.datetime.now().isoformat()
            }
            
            # Filter entities: only save non-empty string values
            filtered_entities = {}
            if ai_response_obj.entities:
                for key, value in ai_response_obj.entities.items():
                    if value is not None and isinstance(value, str) and value.strip():
                        filtered_entities[key] = value.strip()
                    elif value is None:
                        print(f"[{call_sid}] Skipping null entity: {key}")
            
            # Save intent-scoped entities + shared metadata
            profile_service.update_profile_for_intent(
                caller_number, 
                ai_response_obj.intent, 
                filtered_entities,
                shared_metadata
            )
            
            # For logging, show the updated profile merged view
            updated_data = profile_data.copy() if profile_data else {}
            updated_data.update(shared_metadata)
            updated_data.update(filtered_entities)
            
            # Track profile completion
            profile_completion = metrics.check_profile_completion(ai_response_obj.intent, updated_data)
            cloud_logger.log_profile_completion(caller_number, ai_response_obj.intent, profile_completion)
            
            print(f"[{call_sid}] Profile updated for intent '{ai_response_obj.intent}'. New entities: {filtered_entities}")
            print(f"[{call_sid}] Profile completion: {profile_completion['completion_pct']}% ({profile_completion['filled']}/{profile_completion['required']} fields)")
            print(f"[{call_sid}] Full merged profile view: {updated_data}")
        except Exception as e:
            print(f"Error updating profile: {e}")
            metrics.record_error(call_sid, "PROFILE_UPDATE_ERROR", str(e))
            cloud_logger.log_error_event(call_sid, "PROFILE_UPDATE_ERROR", str(e))
    else:
        print(f"[{call_sid}] GUARDRAIL: Skipping profile update due to ERROR intent")
        metrics.record_error(call_sid, "LLM_ERROR_INTENT", "LLM returned ERROR intent")
        cloud_logger.log_error_event(call_sid, "LLM_ERROR_INTENT", "LLM returned ERROR intent")
    
    ai_text = ai_response_obj.reply_text
    action = ai_response_obj.action
    
    # Record metrics: action and completion
    metrics.record_action(call_sid, action)
    call_memory.append({
        "user": text,
        "ai": ai_text,
        "intent": ai_response_obj.intent,
        "entities": ai_response_obj.entities
    })
    call_sessions[call_sid] = call_memory
    
    print(f"[{call_sid}] AI response: {ai_text}")
    print(f"[{call_sid}] Conversation history length: {len(call_memory)}")
    
    VOICE_MAP = {
        "[EN]": {"voice": "Polly.Joanna-Neural", "language": "en-US"},
        "[ES]": {"voice": "Polly.Mia", "language": "es-MX"},
        "[HI]": {"voice": "Polly.Aditi", "language": "hi-IN"},
    }
    
    selected_voice = "Polly.Joanna-Neural"
    selected_language = "en-US"
    clean_text = ai_text
    
    for tag, settings in VOICE_MAP.items():
        if tag in ai_text:
            selected_voice = settings["voice"]
            selected_language = settings["language"]
            clean_text = ai_text.replace(tag, "").strip()
            break
    
    # Check if we should forward the call
    if action == "forward" or ai_response_obj.intent == "ERROR":
        print(f"[{call_sid}] Ready to forward. Intent: {ai_response_obj.intent}")
        
        caller_number = str(form_data.get("From", ""))
        twilio_number = str(form_data.get("To", ""))
        
        # WhatsApp Logic for JOB_SEEKER - send resume upload link
        if ai_response_obj.intent == "JOB_SEEKER":
            try:
                from app.config import settings
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                wa_message = f"Thanks for speaking with Bhuvi IT Solutions! To complete your profile, please upload your resume and documents here: https://athena-natatory-dawn.ngrok-free.dev/upload. Our team will review your information and get back to you shortly!"
                
                client.messages.create(
                    body=wa_message,
                    from_=f"whatsapp:+14155238886",
                    to=f"whatsapp:{caller_number}"
                )
                print(f"[{call_sid}] Success: WhatsApp message sent to {caller_number}")
            except Exception as e:
                print(f"[{call_sid}] Error sending WhatsApp message: {e}")
        
        # Generate call whisper (summary) for the recruiter
        service = get_llm_service()
        call_whisper = await service.generate_call_summary(
            intent=ai_response_obj.intent,
            call_memory=call_memory,
            profile_data=updated_data  # Pass the final profile with all extracted details
        )
        
        print(f"[{call_sid}] Call Whisper: {call_whisper}")
        
        # Clean up session when forwarding
        if call_sid in call_sessions:
            del call_sessions[call_sid]
        
        # Play the AI's actual response first, then pause, then play recruiter brief
        xml_response = f"""
            <Response>
                <Say voice="{selected_voice}">{clean_text}</Say>
                <Pause length="1"/>
                <Say voice="Polly.Joanna-Neural">[RECRUITER BRIEF: {call_whisper}]</Say>
                <Hangup/>
            </Response>
            """
        return Response(content=xml_response, media_type="application/xml")
    
    # Continue conversation
    xml_response = f"""
        <Response>
            <Say voice="Polly.Joanna-Neural">{clean_text}</Say>
            <Pause length="2"/>
            <Record maxLength="30" timeout="2" trim="trim-silence" action="/transcribe" playBeep="false"/>
        </Response>
        """
    
    return Response(content=xml_response, media_type="application/xml")


@app.post("/call-status")
async def call_status_webhook(request: Request):
    """
    Twilio calls this endpoint when call status changes (completed, failed, etc.)
    We use it to clean up conversation memory.
    """
    form_data = await request.form()
    call_sid = str(form_data.get("CallSid", "unknown"))
    call_status = str(form_data.get("CallStatus", "unknown"))
    
    print(f"[{call_sid}] Call status: {call_status}")
    
    # Clean up session when call ends
    if call_status in ["completed", "failed", "busy", "no-answer"]:
        if call_sid in call_sessions:
            conversation_length = len(call_sessions[call_sid])
            print(f"[{call_sid}] Cleaning up session. Had {conversation_length} exchanges.")
            del call_sessions[call_sid]
    
    return Response(content="<Response></Response>", media_type="application/xml")

@app.get("/upload", response_class=HTMLResponse)
async def get_upload_page():
    file_path = os.path.join(os.path.dirname(__file__), "templates", "upload.html")
    try:
        with open(file_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content, status_code=200)
    except FileNotFoundError:
        return HTMLResponse(content="Upload page not found.", status_code=404)

@app.post("/upload-resume")
async def upload_file(file: UploadFile = File(...)):
    """
    Endpoint to receive file uploads (e.g. resumes) from the user.
    We will save the file to Google Drive and return the link.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    
    try:
        content = await file.read()
        drive_service = get_drive_service()
        file_link = await drive_service.upload_file(file.filename, content, file.content_type)
        return {"file_link": file_link}
    except Exception as e:
        print(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file")

@app.get("/metrics")
async def get_metrics():
    """
    Endpoint to retrieve system metrics dashboard.
    Includes call funnel, intent distribution, STT success, errors, user behavior, and latencies.
    """
    metrics = get_metrics_service()
    return metrics.get_aggregated_metrics()

@app.get("/metrics/summary")
async def get_metrics_summary():
    """
    Endpoint to log and return a human-readable summary of metrics.
    Also publishes to Cloud Logging for persistence.
    """
    metrics = get_metrics_service()
    cloud_logger = get_cloud_logging_service()
    
    # Get metrics and log to cloud
    aggregated = metrics.get_aggregated_metrics()
    cloud_logger.log_aggregated_metrics(aggregated)
    
    # Log to console
    metrics.log_metrics_summary()
    
    return {"status": "Metrics logged to console and Cloud Logging", "summary": aggregated}

@app.get("/metrics/call/{call_sid}")
async def get_call_metrics(call_sid: str):
    """
    Get metrics for a specific call.
    """
    metrics = get_metrics_service()
    call_summary = metrics.get_call_summary(call_sid)
    if not call_summary:
        raise HTTPException(status_code=404, detail=f"Call {call_sid} not found")
    return call_summary
