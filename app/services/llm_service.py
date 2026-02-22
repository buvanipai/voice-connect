# app/services/llm_service.py
import json
import os
from pydoc import doc
from typing import Optional
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
        
    async def analyze_call(self, text: str, call_memory: Optional[list] = None) -> AIResponse:
        
        if call_memory is None:
            call_memory = []
        
        results = self.collection.query(
            query_texts=[text],
            n_results=5  # Increased to get more context about jobs
        )
        
        documents = results.get('documents')
        
        if documents and len(documents) > 0:
            retrieved_knowledge = "\n".join(documents[0])
            print(f"Found Context: {retrieved_knowledge}")
        else:
            retrieved_knowledge = "No relevant information found in the knowledge base."
            print("No relevant context found.")
            
        memory_string = json.dumps(call_memory, indent=2)
        
        system_prompt = f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions.
        
        Knowledge Base:
        {retrieved_knowledge}
        
        Past Conversation History:
        {memory_string}
        
        CANDIDATE FLOW (JOB_SEEKER intent):
        If this is their FIRST message about jobs, ask ONE question at a time in this order:
        1. Which specific role are they interested in? (Reference the CURRENT JOB OPENINGS from Knowledge Base if available)
        2. What is their tech stack? (e.g., Python, React, AWS, Java, etc.)
        3. How many years of experience do they have?
        4. Are they willing to relocate or travel to the US for work?
        5. What is their visa status? (US Citizen, Green Card, need TN Visa sponsorship, etc.)
        
        Once you have collected ALL 5 pieces of information OR the user asks for a human, set "action" to "forward".
        
        CLIENT FLOW (CLIENT_LEAD intent):
        1. What roles are they looking to hire for?
        2. What specific skills or tech stack are they looking for?
        3. Do they prefer nearshore talent or US-based?
        
        Once you understand their needs OR they ask for a human, set "action" to "forward".
        
        INTENT CLASSIFICATION:
        - JOB_SEEKER: Asking about jobs, careers, applying for a position, or job openings.
        - CLIENT_LEAD: Companies/businesses wanting to hire developers or build AI products.
        - GENERAL_INQUIRY: Hours, location, company info, or unclear questions.
        
        LANGUAGE TAGS:
        - Use [EN] for English, [ES] for Spanish, [HI] for Hindi at the start of reply_text.
        
        CRITICAL: You MUST respond with ONLY a valid JSON object in this exact format, with no other text:

        {{"intent": "JOB_SEEKER", "confidence": 0.9, "reply_text": "[EN] Your response here", "action": "speak"}}
        
        Do not add any explanation, markdown, or other text. Only output the JSON object.
        """
        
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=300,  # Increased for longer job-related responses
                system=system_prompt,
                messages=[{"role": "user", "content": text}]
            )
            
            # Parse response
            response_block = message.content[0]
            
            if response_block.type == "text":
                raw_content = response_block.text
            else:
                raw_content = "{}" # Fallback to empty JSON if not text
            
            # Clean up markdown code blocks if present
            raw_content = raw_content.strip()
            if raw_content.startswith("```"):
                # Remove markdown code block wrapper
                lines = raw_content.split("\n")
                raw_content = "\n".join(lines[1:-1]) if len(lines) > 2 else raw_content
                raw_content = raw_content.replace("```json", "").replace("```", "").strip()
            
            print(f"Claude Response: {raw_content[:200]}...")  # Debug: show first 200 chars
            
            data = json.loads(raw_content)
            return AIResponse(**data)
            
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error: {e}")
            print(f"Raw content was: {raw_content}")
            return AIResponse(
                intent="ERROR",
                confidence=0.0,
                reply_text="I apologize, but I am having trouble connecting. Please hold.",
                entities=[]
            )
        except Exception as e:
            # Log the error in production (print for now)
            print(f"LLM Error: {e}")
            return AIResponse(
                intent="ERROR",
                confidence=0.0,
                reply_text="I apologize, but I am having trouble connecting. Please hold.",
                entities=[]
            )