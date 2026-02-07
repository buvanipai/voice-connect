# app/services/llm_service.py
import json
import anthropic
from app.config import settings
from app.schemas import AIResponse

class LLMService:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.MODEL_NAME
        
    async def analyze_call(self, text: str) -> AIResponse:
        system_prompt = """
        You are the Voice AI Receptionist for Bhuvi IT Solutions.
        Classify the caller's intent and generate a brief voice response.
        
        Intents:
        - JOB_SEEKER: Asking about jobs, careers, or application status.
        - CLIENT_LEAD: Companies wanting to hire developers.
        - GENERAL_INQUIRY: Hours, location, or unknown questions.
        
        Output JSON ONLY:
        {
            "intent": "string",
            "confidence": float,
            "entities": ["list", "of", "words"],
            "reply_text": "Short spoken response (under 2 sentences)."
        }
        """
        
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                system=system_prompt,
                messages=[{"role": "user", "content": text}]
            )
            
            # Parse response
            raw_content = message.content[0].text
            data = json.loads(raw_content)
            return AIResponse(**data)
            
        except Exception as e:
            # Log the error in production (print for now)
            print(f"LLM Error: {e}")
            return AIResponse(
                intent="ERROR",
                confidence=0.0,
                reply_text="I apologize, but I am having trouble connecting. Please hold.",
                entities=[]
            )