# app/main.py
from fastapi import FastAPI, HTTPException, Request, Response
from app.schemas import CallPayload, AIResponse
from app.services.llm_service import LLMService

app = FastAPI(title="VoiceConnect API", version="0.1.0")

# Initialize Service
llm_service = LLMService()

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
    Twilio hits this endpoint when the phone rings.
    We return XML instructions telling it to speak.
    """
    # Simple XML response (TwiML)
    xml_response = """<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="alice">Hello! This is Voice Connect running on Google Cloud. The system is fully operational.</Say>
            <Pause length="1"/>
            <Say>Please check your deployment logs for the next steps. Goodbye.</Say>
        </Response>
        """
    # Return as XML so Twilio understands it
    return Response(content=xml_response, media_type="application/xml")