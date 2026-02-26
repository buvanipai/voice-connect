# app/schemas.py
from pydantic import BaseModel, Field
from typing import Any, Optional, List, Dict, Union

class CallPayload(BaseModel):
    caller_id: Optional[str] = Field(None, description="Caller's phone number")
    text: str = Field(..., description="The spoken text from the user")
    language: str = Field("en", description="Detected language (en, hi, ta)")

class AIResponse(BaseModel):
    intent: str = Field(default="GENERAL_INQUIRY", description="Detected intent (JOB_SEEKER, CLIENT, etc.)")
    confidence: float = Field(default=0.0, description="0.0 to 1.0 score")
    entities: Dict[str, Any] = Field(default_factory=dict, description="Key extracted entities (role, experience, visa, etc.)")
    reply_text: str = Field(..., description="What the AI voice should say back")
    action: str = "speak"