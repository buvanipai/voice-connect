# app/services/llm_service.py
import json
import os
from pydoc import doc
import chromadb
import anthropic
from app.config import settings
from app.schemas import AIResponse
from chromadb.utils import embedding_functions

class LLMService:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.MODEL_NAME
        
        db_path = "./chroma_db"
        
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        
        self.chroma_client = chromadb.PersistentClient(path=db_path)
        self.collection = self.chroma_client.get_collection(
            name="bhuvi_knowledge",
            embedding_function=self.embedding_fn # type: ignore
        )
        print("Connected to Knowledge Base!")
        
    async def analyze_call(self, text: str) -> AIResponse:
        
        results = self.collection.query(
            query_texts=[text],
            n_results=2
        )
        
        documents = results.get('documents')
        
        if documents and len(documents) > 0:
            retrieved_knowledge = "\n".join(documents[0])
            print(f"Found Context: {retrieved_knowledge}")
        else:
            retrieved_knowledge = "No relevant information found in the knowledge base."
            print("No relevant context found.")
        
        system_prompt = f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions.
        Your goal is to classify intent, use the Knowledge Base, AND match the user's language.
        
        Knowledge Base:
        {retrieved_knowledge}
        
        LANGUAGE INSTRUCTIONS:
        1. If the user speaks English -> Start reply_text with [EN].
        2. If the user speaks Spanish -> Start reply_text with [ES].
        3. If the user speaks Hindi or Hinglish -> Start reply_text with [HI].
        
        INTENT INSTRUCTIONS:
        - JOB_SEEKER: Asking about jobs, careers, or application status.
        - CLIENT_LEAD: Companies wanting to hire developers.
        - GENERAL_INQUIRY: Hours, location, or unknown questions.
        
        RESPONSE INSTRUCTIONS:
        - If the user asks about a topic in the Knowledge Base, YOU MUST MENTION THE SPECIFIC DETAILS (e.g., "TN Visa", "Nearshore").
        - Keep the 'reply_text' natural and conversational (under 2 sentences).
        
        Output JSON ONLY:
        {{
            "intent": "string",
            "confidence": float,
            "reply_text": "[TAG] Short spoken response in the user's language."
        }}
        """
        
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=200,
                system=system_prompt,
                messages=[{"role": "user", "content": text}]
            )
            
            # Parse response
            response_block = message.content[0]
            
            if response_block.type == "text":
                raw_content = response_block.text
            else:
                raw_content = "{}" # Fallback to empty JSON if not text
            
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