from pydantic import BaseModel, Field
from typing import Optional, List

# What Rockscar sends YOU
class CallPayload(BaseModel):
    caller_id: Optional[str] = Field(None, description="Caller's phone number")
    text: str = Field(..., description="The spoken text from the user")
    language: str = Field("en", description="Detected language (en, hi, ta)")

# What YOU send back
class AIResponse(BaseModel):
    intent: str = Field(..., description="Detected intent (JOB_SEEKER, CLIENT, etc.)")
    confidence: float = Field(..., description="0.0 to 1.0 score")
    entities: List[str] = Field(default_factory=list, description="Key extracted terms")
    reply_text: str = Field(..., description="What the AI voice should say back")