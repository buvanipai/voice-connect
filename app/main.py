# app/main.py
import select
from dotenv import load_dotenv
import twilio
load_dotenv()
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
from pydoc import text
from typing import Dict, List
from fastapi import FastAPI, HTTPException, Request, Response
from app.schemas import CallPayload, AIResponse
from app.services.llm_service import LLMService
from app.services.stt_service import DeepgramSTT
from twilio.rest import Client

app = FastAPI(title="VoiceConnect API", version="0.1.0")

_llm_service_instance = None
_stt_instance = None

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
    
    # Initialize conversation history for this call
    if call_sid not in call_sessions:
        call_sessions[call_sid] = []
        print(f"[NEW CALL] CallSid: {call_sid}")
    
    # Simple XML response (TwiML)
    xml_response = """
        <Response>
            <Say voice="Polly.Joanna-Neural">Hello! Thank you for calling Bhuvi IT Solutions. To route you to the right team, are you calling to apply for a job, looking to hire IT talent, or interested in our custom AI development services?</Say>
            <Record maxLength="10" timeout="2" action="/transcribe" playBeep="true"/>
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
    
    if not recording_url:
        return Response(content="<Response><Say>I didn't hear anything.</Say></Response>", media_type="application/xml")
    
    # Deepgram to convert audio to text
    stt = get_stt_service()
    text = await stt.transcribe(recording_url)
    
    print(f"[{call_sid}] User said: {text}")
    
    if not text or not text.strip():
        print("User was silent. Asking them to repeat.")
        return Response(
            content="<Response><Say>I didn't catch that. Could you please repeat?</Say><Record maxLength='10' timeout='3' action='/transcribe' playBeep='true'/></Response>", 
            media_type="application/xml"
        )
    
    # Get conversation history for this call
    call_memory = call_sessions.get(call_sid, [])
    
    service = get_llm_service()
    ai_response_obj = await service.analyze_call(text, call_memory=call_memory, caller_country=caller_country, caller_state=caller_state)
    ai_text = ai_response_obj.reply_text
    action = ai_response_obj.action
    
    # Store this exchange in memory
    call_memory.append({
        "user": text,
        "ai": ai_text,
        "intent": ai_response_obj.intent
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
        
        # Determine message based on intent
        if ai_response_obj.intent == "ERROR":
            forward_message = ai_response_obj.reply_text
        elif ai_response_obj.intent == "JOB_SEEKER":
            forward_message = "Thank you for your interest! Let me forward you to a recruiter who can assist you further."
            
            # SMS Logic
            try:
                from app.config import settings
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                sms_text = f"Thanks for speaking with Bhuvi IT Solutions! To complete your profile, please upload your resume and documents here: https://bhuviits.com/apply. Our team will review your information and get back to you shortly!"
                
                client.messages.create(
                    body=sms_text,
                    from_=twilio_number,
                    to=caller_number
                )
                print(f"[{call_sid}] Success: SMS sent to {caller_number}")
            except Exception as e:
                print(f"Error sending SMS: {e}")
            
        elif ai_response_obj.intent == "CLIENT_LEAD":
            forward_message = "Thank you for reaching out! Let me forward you to our representative who can discuss your needs."
        else:
            forward_message = "Thank you for calling. Let me connect you to our team."
        
        # Generate call whisper (summary) for the recruiter
        service = get_llm_service()
        call_whisper = await service.generate_call_summary(
            intent=ai_response_obj.intent,
            call_memory=call_memory
        )
        
        print(f"[{call_sid}] Call Whisper: {call_whisper}")
        
        # Clean up session when forwarding
        if call_sid in call_sessions:
            del call_sessions[call_sid]
        
        # For testing: Play end message + whisper, then hang up
        # In production, you'd dial Subbu and play whisper to them
        xml_response = f"""
            <Response>
                <Say voice="Polly.Joanna-Neural">{forward_message}</Say>
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
            <Pause length="1"/>
            <Record maxLength="30" timeout="2" action="/transcribe" playBeep="true"/>
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