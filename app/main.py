# app/main.py
from fastapi import FastAPI, HTTPException
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