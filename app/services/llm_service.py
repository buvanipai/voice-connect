# app/services/llm_service.py
import json
import os
from pydoc import doc
from typing import Optional, List
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
    
    def _check_location_match(self, caller_location: str) -> bool:
        """Check if caller's location matches any available job locations."""
        if not caller_location or isinstance(caller_location, str) and not caller_location.strip():
            return False
        try:
            caller_loc_lower = str(caller_location).lower().strip()
            for job_loc in settings.JOB_LOCATIONS:
                if caller_loc_lower in job_loc.lower() or job_loc.lower() in caller_loc_lower:
                    return True
        except (AttributeError, TypeError):
            pass
        return False
    
    def _check_job_seeker_missing(self, profile: dict, caller_location: str) -> List[str]:
        """Check which fields are missing for JOB_SEEKER candidates.
        Returns list of missing field names.
        """
        required = ["role_interest", "experience_years", "tech_stack", "caller_location", "visa_status"]
        missing = []
        
        # Sanitize inputs
        profile = profile or {}
        caller_location = str(caller_location).strip() if caller_location else ""
        
        for field in required:
            if field == "caller_location":
                # Check if we have caller's location
                if not caller_location or caller_location.lower() == "unknown":
                    missing.append(field)
            else:
                # Check if field exists and has content
                field_value = profile.get(field)
                if not field_value or (isinstance(field_value, str) and not field_value.strip()):
                    missing.append(field)
        
        # If location is known but doesn't match jobs, add relocation query to missing
        if "caller_location" not in missing and caller_location and caller_location.lower() != "unknown":
            if not self._check_location_match(caller_location):
                missing.append("relocation_willing")
        
        return missing
        
    async def analyze_call(self, text: str, call_memory: Optional[list] = None, caller_country: str = "Unknown", caller_state: str = "Unknown", user_profile: Optional[dict] = None) -> AIResponse:
        
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
        
        # --- MERGE MEMORY INTO CURRENT PROFILE ---
        current_profile = user_profile.copy() if user_profile else {}
        for exchange in call_memory:
            if exchange.get("entities"):
                current_profile.update(exchange["entities"])
        
        # --- DETERMINE WHAT'S MISSING (PYTHON LOGIC) ---
        missing_fields = self._check_job_seeker_missing(current_profile, caller_state)
        
        # --- LOCATION-BASED JOB MATCH ---
        available_jobs = ", ".join(settings.JOB_LOCATIONS)
        location_context = ""
        if current_profile.get("caller_location"):
            if self._check_location_match(current_profile["caller_location"]):
                location_context = f"Caller is in {current_profile['caller_location']}, which matches our job locations: {available_jobs}."
            else:
                location_context = f"Caller is in {current_profile['caller_location']}, but we have jobs in: {available_jobs}. We may need to ask about relocation."
        
        # --- VISA RULES ---
        if caller_country == "US":
            visa_rule = "- Ask for their current US work authorization (e.g., US Citizen, Green Card, H1B)."
        else:
            visa_rule = "- Caller is International. Ask about US visa status and sponsorship requirements."
        
        # --- BUILD USER CONTEXT ---
        user_context = "No prior profile found."
        if current_profile:
            # Only include fields that have actual content
            known_facts = [
                f"{k}: {v}" for k, v in current_profile.items() 
                if v and (isinstance(v, str) and v.strip() or not isinstance(v, str))
                and k in ['role_interest', 'experience_years', 'visa_status', 'tech_stack', 'caller_location']
            ]
            if known_facts:
                user_context = f"KNOWN PROFILE DATA: {', '.join(known_facts)}. DO NOT ASK FOR THESE."

        # --- THE OPTIMIZED SYSTEM PROMPT ---
        system_prompt = f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions.
        
        CONTEXT:
        {user_context}
        {location_context}
        {visa_rule}
        
        KNOWLEDGE BASE (For answering general questions):
        {retrieved_knowledge}
        
        INTENT CLASSIFICATION & GOALS:
        Categorize the user into one of these intents and follow the specific rules:

        1. JOB_SEEKER (Candidate looking for a job)
           - GOAL: Collect 5 details: Role Interest, Tech Stack, Experience Years, Caller Location (where they are), Visa Status.
           - If location doesn't match available jobs ({available_jobs}), also confirm they are willing to relocate.
           - {location_context}
           - CRITICAL: Once all details are collected, you MUST say: "I am sending a text message with a link for you to upload your resume and connecting you with our recruiter for the next steps."
           - NEVER ask for email address, phone number, or any other contact information. The system handles everything via SMS.
           - After confirming all details are collected, set "action": "forward" immediately.
           - DO NOT ask for email, phone, name, or personal contact info under any circumstances.

        2. CLIENT_LEAD (Company looking to hire talent or build products)
           - GOAL: Collect 3 details: Roles they are hiring for, Tech stack needed, Preference for nearshore vs US-based.
           - Once all 3 are collected, set "action": "forward".

        3. GENERAL_INQUIRY (Questions about the company, hours, location)
           - GOAL: Answer their questions using ONLY the Knowledge Base.
           - Keep answering until they are satisfied. 
           - Set "action": "forward" ONLY if they explicitly ask to speak to a human.

        ENTITY EXTRACTION (JOB_SEEKER):
        Extract these fields from the conversation:
        - "role_interest": Job title or role they want (e.g., "Python Developer", "Data Engineer")
        - "tech_stack": Technologies they know or want to work with (e.g., "Python, React, AWS")
        - "experience_years": Years of professional experience (e.g., "3", "5+")
        - "caller_location": Where they are currently located (e.g., "Chicago, IL", "Texas", "Austin")
        - "visa_status": Their work authorization status in the US (e.g., "US Citizen", "Green Card", "Need H1B sponsorship")
        - "relocation_willing": (ONLY if location doesn't match jobs) Whether they're willing to relocate/work onsite (e.g., "Yes", "No", "Open to discussing")
        
        CRITICAL INSTRUCTION ON MEMORY & STATE (APPLIES TO ALL INTENTS):
        You will see your past responses in the chat history as JSON objects.
        CHECK the "entities" field in those past JSON objects.
        - Silently cross off the details the user has ALREADY provided.
        - ONLY ask questions about the details that are STILL MISSING.
        - DO NOT EVER repeat a question if the user already answered it.
        
        STATE CARRY-OVER RULE:
        You must OUTPUT the cumulative list of all entities collected so far.
        If you found "role_interest" in turn 1, you MUST include "role_interest" in your JSON output for turn 2, turn 3, etc.
        
        INTERACTION STYLE:
        - Keep responses to 1-2 short sentences maximum.
        - Ask ONE question at a time.
        
        OUTPUT FORMAT:
        Return ONLY a valid JSON object. No markdown, no explanations.
        {{
            "intent": "CLIENT_LEAD",
            "confidence": 0.95,
            "entities": {{
                "hiring_roles": "Data Scientists",
                "hiring_preference": "US-based"
            }},
            "reply_text": "[EN] Excellent. And what specific tech stack or skills are you looking for in these Data Scientists?",
            "action": "speak"
        }}
        
        CRITICAL INSTRUCTION: You MUST output ONLY valid JSON. Do not include any conversational text, pleasantries or explanations outside of the JSON block. Your entire response must be parseable by Python's json.loads().
        
        """

        # --- REBUILD CHAT HISTORY WITH ENTITIES ---
        chat_messages = []
        for exchange in call_memory:
            if exchange.get("user"):
                chat_messages.append({"role": "user", "content": exchange["user"]})
            if exchange.get("ai"):
                saved_intent = exchange.get("intent", "GENERAL_INQUIRY")
                safe_ai_text = exchange["ai"].replace('"', "'")
                
                # REINJECTING MEMORY:
                # We feed the saved entities back into the history so Claude sees what it already knows.
                saved_entities = exchange.get("entities", {}) 
                entities_json = json.dumps(saved_entities)
                
                fake_json = f'{{"intent": "{saved_intent}", "confidence": 0.9, "entities": {entities_json}, "reply_text": "{safe_ai_text}", "action": "speak"}}'
                chat_messages.append({"role": "assistant", "content": fake_json})
        
        chat_messages.append({"role": "user", "content": text})
        
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=250,  # Reduced to enforce brevity and prevent webhook timeouts
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
            
            # Extract JSON from response (handles text preambles like "Alright, here's...")
            # Find first { and parse from there
            json_start = raw_content.find('{')
            if json_start != -1:
                raw_content = raw_content[json_start:]
            
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
                entities={}
            )
        except Exception as e:
            # Log the error in production (print for now)
            print(f"LLM Error: {e}")
            return AIResponse(
                intent="ERROR",
                confidence=0.0,
                reply_text="I apologize, but I am having technical difficulties. Please hold I'm connecting you to a representative.",
                action="forward",
                entities={}
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
        Based on this phone conversation, generate a BRIEF 2 sentence summary that a recruiter will hear as a "call whisper" before the call connects.
        The summary should:
        1. Be under 20 seconds when spoken (roughly 50 words max)
        2. Include caller's intent/needs
        3. Include key details (role, experience, tech stack, visa status, etc.) if a JOB_SEEKER
        4. Include hiring needs and preferences if CLIENT_LEAD
        5. Be professional and concise and in third person only.
        6. Sound natural when read aloud
        
        Intent: {intent}
        
        Conversation:
        {transcript}
        
        Generate ONLY 2 short sentences, nothing else:
        """
        
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=150,  # Reduced for faster generation
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