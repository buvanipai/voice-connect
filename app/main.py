# app/main.py
import select
from dotenv import load_dotenv
load_dotenv()
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
from pydoc import text
from fastapi import FastAPI, HTTPException, Request, Response
from app.schemas import CallPayload, AIResponse
from app.services.llm_service import LLMService
from app.services.stt_service import DeepgramSTT

app = FastAPI(title="VoiceConnect API", version="0.1.0")

# Initialize Service
try:
    llm_service = LLMService()
except Exception as e:
    print(f"Error initializing LLMService: {str(e)}")
    import traceback
    traceback.print_exc()

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
        
    result = await llm_service.analyze_call(payload.text)
    return result

# Phone endpoint for Twilio
@app.post("/voice")
async def voice_webhook(request: Request):
    """
    Step 1: Answer and ask the user to speak
    Twilio hits this endpoint when the phone rings.
    We return XML instructions telling it to speak.
    """
    # Simple XML response (TwiML)
    xml_response = """
        <Response>
            <Say voice="alice">Hello! I'm the Bhuvi IT Assistant. How can I help you?</Say>
            <Record maxLength="10" timeout="2" trim="trim-silence" action="/transcribe" playBeep="true"/>
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
    
    if not recording_url:
        return Response(content="<Response><Say>I didn't hear anything.</Say></Response>", media_type="application/xml")
    
    # Deepgram to convert audio to text
    stt = DeepgramSTT()
    text = await stt.transcribe(recording_url)
    
    print(f"User said: {text}")
    
    ai_response_obj = await llm_service.analyze_call(text)
    ai_text = ai_response_obj.reply_text
    print(f"AI response: {ai_text}")
    
    VOICE_MAP = {
        "[EN]": {"voice": "alice", "language": "en-US"},
        "[ES]": {"voice": "Polly.Mia", "language": "es-MX"},
        "[HI]": {"voice": "Polly.Aditi", "language": "hi-IN"},
    }
    
    selected_voice = "alice"
    selected_language = "en-US"
    clean_text = ai_text
    
    for tag, settings in VOICE_MAP.items():
        if tag in ai_text:
            selected_voice = settings["voice"]
            selected_language = settings["language"]
            clean_text = ai_text.replace(tag, "").strip()
            break
    
    # Echo back to user
    xml_response = f"""
        <Response>
            <Say voice="alice">{ai_text}</Say>
            <Pause length="1"/>
            <Record maxLength="30" timeout="2" trim="trim-silence" action="/transcribe" playBeep="true"/>
        </Response>
        """
    
    # For now, just return the URL (later we will call Deepgram)
    return Response(content=xml_response, media_type="application/xml")