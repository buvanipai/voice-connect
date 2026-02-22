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
        
        system_prompt = f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions.
        
        Knowledge Base:
        {retrieved_knowledge}
        
        CANDIDATE FLOW (JOB_SEEKER intent):
        Your goal is to collect these 5 specific details from the caller:
        1. Specific role of interest
        2. Tech stack / Skills
        3. Years of experience
        4. Willingness to relocate or travel to the US
        5. Current visa status (e.g., F1 OPT, TN, H1B, Citizen)
        
        CRITICAL STATE-TRACKING RULES:
        - Read the "Past Conversation History" carefully. 
        - Silently cross off the details the user has ALREADY provided.
        - ONLY ask questions about the details that are STILL MISSING.
        - DO NOT EVER repeat a question if the user already answered it in a previous turn.
        - Once you have collected ALL 5 pieces of information, OR the user asks for a human, set "action" to "forward".

        CLIENT FLOW (CLIENT_LEAD intent):
        Your goal is to collect:
        1. Roles they are hiring for
        2. Specific tech stack/skills needed
        3. Preference for nearshore vs. US-based talent
        - Apply the exact same CRITICAL STATE-TRACKING RULES above. Do not repeat questions. Set "action" to "forward" when complete.
        
        INTENT CLASSIFICATION:
        - JOB_SEEKER: Asking about jobs, careers, applying for a position, or job openings.
        - CLIENT_LEAD: Companies/businesses wanting to hire developers or build AI products.
        - GENERAL_INQUIRY: Hours, location, company info, or unclear questions.
        
        LANGUAGE TAGS:
        - Use [EN] for English, [ES] for Spanish, [HI] for Hindi at the start of reply_text.
        
        CRITICAL OUTPUT FORMAT:
        You MUST respond with ONLY a valid JSON object. 
        DO NOT use line breaks, bullet points, or numbered lists inside the reply_text value. Keep reply_text as a single, continuous paragraph string.
        Output exactly this format:
        {{"intent": "JOB_SEEKER", "confidence": 0.9, "reply_text": "[EN] Your single paragraph response here.", "action": "speak"}}
        
        Do not add any explanation, markdown, or other text. Only output the JSON object.
        """
        chat_messages = []
        for exchange in call_memory:
            if exchange.get("user"):
                chat_messages.append({"role": "user", "content": exchange["user"]})
            if exchange.get("ai"):
                saved_intent = exchange.get("intent", "GENERAL_INQUIRY")
                safe_ai_text = exchange["ai"].replace('"', "'")
                fake_json = f'{{"intent": "{saved_intent}", "confidence": 0.9, "reply_text": "{safe_ai_text}", "action": "speak"}}'
                chat_messages.append({"role": "assistant", "content": fake_json})
        chat_messages.append({"role": "user", "content": text})
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=300,  # Increased for longer job-related responses
                system=system_prompt,
                messages=chat_messages
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
            
            raw_content = raw_content.replace("\n", " ").replace("\r", " ")
            data = json.loads(raw_content)
            return AIResponse(**data)
            
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error: {e}")
            print(f"Raw content was: {raw_content}")
            return AIResponse(
                intent="ERROR",
                confidence=0.0,
                reply_text="I apologize, but I am having technical difficulties. Please hold I'm connecting you to a representative.",
                action="forward",
                entities=[]
            )
        except Exception as e:
            # Log the error in production (print for now)
            print(f"LLM Error: {e}")
            return AIResponse(
                intent="ERROR",
                confidence=0.0,
                reply_text="I apologize, but I am having technical difficulties. Please hold I'm connecting you to a representative.",
                action="forward",
                entities=[]
            )
    
    async def generate_call_summary(self, intent: str, call_memory: list) -> str:
        """
        Generate a concise call summary (whisper) for the recruiter/representative.
        This will be played to Subbu before connecting the call.
        """
        if not call_memory:
            return "No information collected from the call."
        
        # Build a conversation transcript for Claude
        transcript = ""
        for exchange in call_memory:
            transcript += f"Caller: {exchange.get('user', 'N/A')}\n"
            transcript += f"AI: {exchange.get('ai', 'N/A')}\n\n"
        
        summary_prompt = f"""
        Based on this phone conversation, generate a BRIEF 2-3 sentence summary that a recruiter will hear as a "call whisper" before the call connects.
        The summary should:
        1. Be under 30 seconds when spoken (roughly 75 words max)
        2. Include caller's intent/needs
        3. Include key details (role, experience, tech stack, visa status, etc.) if a JOB_SEEKER
        4. Include hiring needs and preferences if CLIENT_LEAD
        5. Be professional and concise
        6. Sound natural when read aloud
        
        Intent: {intent}
        
        Conversation:
        {transcript}
        
        Generate ONLY the summary text, nothing else:
        """
        
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=150,
                messages=[{"role": "user", "content": summary_prompt}]
            )
            
            response_block = message.content[0]
            
            if response_block.type == "text":
                summary = response_block.text.strip()
            else:
                summary = "Call summary generation failed. Please manually brief the staff."
            
            print(f"Generated Call Whisper: {summary}")
            return summary
            
        except Exception as e:
            print(f"Error generating summary: {e}")
            return "Call summary generation failed. Please manually brief the staff."