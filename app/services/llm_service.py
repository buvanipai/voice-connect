# app/services/llm_service.py
import json
import os
from pydoc import doc
from typing import Dict, Optional, List
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
    
    def _check_job_seeker_missing(self, profile: dict) -> List[str]:
        """Check which fields are missing for JOB_SEEKER candidates.
        
        CONVERSATIONAL FLOW:
        1. role_interest, experience_years, tech_stack (basic info)
        2. caller_location (WHERE are they?) - THIS TRIGGERS CONDITIONAL LOGIC
           If US:
             - caller_state (which state?)
             - visa_status (work authorization)
             - visa_sponsorship (do they need sponsorship?)
           If NOT US (and in TN visa countries):
             - visa_sponsorship_preference (nearshore/remote/visa help?)
        3. relocation_willing (if location doesn't match job locations)
        """
        profile = profile or {}
        missing = []
        
        # PHASE 1: Basic professional info (always required)
        required_base = ["role_interest", "experience_years", "tech_stack"]
        for field in required_base:
            field_value = profile.get(field)
            if not field_value or (isinstance(field_value, str) and not field_value.strip()):
                missing.append(field)
        
        # PHASE 2: Location (this is THE critical question that gates everything)
        caller_location = profile.get("caller_location")
        if not caller_location or (isinstance(caller_location, str) and not caller_location.strip()):
            missing.append("caller_location")  # Ask "Where are you located?"
            return missing  # Stop here - everything else depends on location answer
        
        # At this point, we know their location. Determine what location-based questions to ask.
        location_str = str(caller_location).lower().strip()
        is_us = "us" in location_str or "usa" in location_str or "united states" in location_str or "america" in location_str
        
        if is_us:
            # US CALLER: Ask for state, then work authorization, then sponsorship
            caller_state = profile.get("caller_state")
            if not caller_state or (isinstance(caller_state, str) and not caller_state.strip()):
                missing.append("caller_state")  # Ask "Which state?"
                return missing  # Stop - can't ask visa questions until we know their state
            
            # Now ask about work authorization
            visa_status = profile.get("visa_status")
            if not visa_status or (isinstance(visa_status, str) and not visa_status.strip()):
                missing.append("visa_status")  # Ask "What's your work authorization status?"
                return missing
            
            # Now ask if they need sponsorship
            visa_sponsorship = profile.get("visa_sponsorship")
            if not visa_sponsorship or (isinstance(visa_sponsorship, str) and not visa_sponsorship.strip()):
                missing.append("visa_sponsorship")  # Ask "Do you need visa sponsorship?"
                return missing
        else:
            # INTERNATIONAL CALLER: Ask about visa sponsorship/nearshore/remote preferences
            visa_sponsorship_pref = profile.get("visa_sponsorship_preference")
            if not visa_sponsorship_pref or (isinstance(visa_sponsorship_pref, str) and not visa_sponsorship_pref.strip()):
                missing.append("visa_sponsorship_preference")  # Ask about options
                return missing
        
        # PHASE 3: Relocation (only if location doesn't match job locations)
        # Check if their location matches any job location
        if not self._check_location_match(caller_location):
            relocation_willing = profile.get("relocation_willing")
            if not relocation_willing or (isinstance(relocation_willing, str) and not relocation_willing.strip()):
                missing.append("relocation_willing")  # Ask "Are you open to relocate?"
        
        return missing

    def _is_missing_value(self, value: Optional[object]) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    def _extract_first_json_object(self, text: str) -> Optional[dict]:
        """Extract the first valid JSON object from model output."""
        if not text:
            return None

        decoder = json.JSONDecoder()
        start = text.find("{")

        while start != -1:
            fragment = text[start:]
            try:
                parsed, end_index = decoder.raw_decode(fragment)
                if isinstance(parsed, dict):
                    trailing = fragment[end_index:].strip()
                    if trailing:
                        print(f"⚠️  Claude returned trailing text after JSON: {trailing[:120]}")
                    return parsed
            except json.JSONDecodeError:
                pass

            start = text.find("{", start + 1)

        return None

    def _check_missing_fields(self, branch: str, profile: dict) -> List[str]:
        profile = profile or {}
        normalized_branch = (branch or "GENERAL_INQUIRY").upper()

        if normalized_branch == "JOB_SEEKER":
            return self._check_job_seeker_missing(profile)

        required_by_branch: Dict[str, List[str]] = {
            "US_STAFFING": ["hiring_role", "tech_stack", "location_preference", "timeline"],
            "AI_CAREER_DEV": ["current_background", "ai_goal", "experience_level"],
            "AI_SMALL_BIZ": ["business_type", "pain_point", "current_tools"],
            "AI_PROD_DEV": ["product_idea", "target_user", "timeline"],
        }

        required_fields = required_by_branch.get(normalized_branch, [])
        return [field for field in required_fields if self._is_missing_value(profile.get(field))]
        
    async def analyze_call(self, text: str, call_memory: Optional[list] = None, caller_country: str = "Unknown", caller_state: str = "Unknown", user_profile: Optional[dict] = None, branch: Optional[str] = None) -> AIResponse:
        
        if call_memory is None:
            call_memory = []
        
        # DEBUG: Uncomment the line below to test international caller logic
        # caller_country = "India"  # Force international for testing
        
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
        
        print(f"[LLM CONTEXT] Starting profile: {current_profile}")
        print(f"[LLM CONTEXT] Call memory length: {len(call_memory)} exchanges")

        active_branch = (branch or current_profile.get("last_intent") or "GENERAL_INQUIRY").upper()
        if active_branch == "CLIENT_LEAD":
            active_branch = "US_STAFFING"
        supported_branches = {
            "JOB_SEEKER",
            "US_STAFFING",
            "AI_CAREER_DEV",
            "AI_SMALL_BIZ",
            "AI_PROD_DEV",
            "GENERAL_INQUIRY",
        }
        if active_branch not in supported_branches:
            active_branch = "GENERAL_INQUIRY"
        print(f"[LLM CONTEXT] Active branch: {active_branch}")
        
        # --- DETERMINE WHAT'S MISSING (PYTHON LOGIC) ---
        missing_fields = self._check_missing_fields(active_branch, current_profile)
        
        # --- LOCATION-BASED JOB MATCH ---
        available_jobs = ", ".join(settings.JOB_LOCATIONS)
        location_context = ""
        
        # Use caller_state from Twilio as the primary location source
        caller_location_to_check = current_profile.get("caller_location") or caller_state
        
        if caller_location_to_check and caller_location_to_check.lower() != "unknown":
            if self._check_location_match(caller_location_to_check):
                location_context = f"Caller is in {caller_location_to_check}, which matches our job locations: {available_jobs}."
            else:
                location_context = f"Caller is in {caller_location_to_check}, but we have jobs in: {available_jobs}. We may need to ask about relocation or nearshore options."
        
        # --- VISA RULES (country-specific) ---
        if caller_country == "US":
            visa_rule = "- Ask for their current US work authorization (e.g., US Citizen, Green Card, H1B)."
        elif caller_country == "MX":
            visa_rule = "- Caller is from Mexico. Offer TN Visa sponsorship - it's faster and easier than H1B for Mexican citizens. Ask if they need visa sponsorship."
        else:
            visa_rule = "- Caller is International. Ask about US visa status and sponsorship requirements."
        
        # --- BUILD USER CONTEXT ---
        user_context = "No prior profile found."
        if current_profile:
            # Only include fields that have actual content
            known_facts = [
                f"{k}: {v}" for k, v in current_profile.items() 
                if v and (isinstance(v, str) and v.strip() or not isinstance(v, str))
                and k in [
                    'role_interest', 'experience_years', 'visa_status', 'tech_stack', 'caller_location',
                    'caller_state', 'visa_sponsorship', 'visa_sponsorship_preference', 'relocation_willing',
                    'hiring_role', 'location_preference', 'timeline', 'current_background', 'ai_goal',
                    'experience_level', 'business_type', 'pain_point', 'current_tools',
                    'product_idea', 'target_user', 'budget_range'
                ]
            ]
            if known_facts:
                user_context = f"KNOWN PROFILE DATA: {', '.join(known_facts)}. DO NOT ASK FOR THESE."
        
        # --- BUILD MISSING FIELDS INSTRUCTION ---
        missing_fields_instruction = ""
        if missing_fields:
            missing_fields_str = ", ".join(missing_fields)
            missing_fields_instruction = f"\nCRITICAL: You MUST focus on collecting these MISSING fields from the user:\n{missing_fields_str}\n\nDO NOT ask about any other fields. DO NOT extract fields that the user has not explicitly provided."

        # --- BRANCH-SPECIFIC SYSTEM PROMPTS ---
        common_json_contract = """
        CRITICAL INSTRUCTION ON MEMORY & STATE:
        You will see your past responses in the chat history as JSON objects.
        CHECK the "entities" field in those past JSON objects.
        - Silently cross off the details the user has ALREADY provided.
        - ONLY ask questions about the details that are STILL MISSING.
        - DO NOT EVER repeat a question if the user already answered it.

        STATE CARRY-OVER RULE:
        You must OUTPUT the cumulative list of all entities collected so far.

        INTERACTION STYLE:
        - Keep responses to 1-2 short sentences maximum.
        - Ask ONE question at a time.

        MANDATORY JSON OUTPUT FORMAT:
        Your response MUST ALWAYS be ONLY a valid JSON object.
        Required fields: intent, confidence, entities, reply_text, action, branch.
        Example:
        {{"intent": "US_STAFFING", "confidence": 0.95, "entities": {{"hiring_role": "Backend Engineer"}}, "reply_text": "Thanks. What tech stack do you need?", "action": "speak", "branch": "US_STAFFING"}}
        """

        job_seeker_prompt = f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions.
        
        CONTEXT:
        {user_context}
        {location_context}
        {visa_rule}{missing_fields_instruction}
        
        KNOWLEDGE BASE (For answering general questions):
        {retrieved_knowledge}
        
        INTENT CLASSIFICATION & GOALS:
        Categorize the user into one of these intents and follow the specific rules:

        1. JOB_SEEKER (Candidate looking for a job)
           
           SPECIAL CASE - RETURNING CALLER PROFILE CONFIRMATION:
           If the conversation history shows we asked "Is this still accurate?" and the user confirms (says "yes", "correct", "accurate", "that's right", etc.):
           - Set action: "forward" immediately
           - Reply: "Great! I'm sending a text with a resume upload link and connecting you with our recruiter now."
           - Keep all existing entities from their profile
           - DO NOT ask any more questions
           
           CONVERSATION FLOW (for new callers or profile updates):
           
           STEP 1: Basic Professional Info
           - Ask: "What role are you interested in?"
           - Ask: "What's your tech stack or main technologies?"
           - Ask: "How many years of professional experience do you have?"
           - Extract: role_interest, tech_stack, experience_years
           
           STEP 2: Location & Visa (THE CRITICAL GATING QUESTION)
           - Ask: "Where are you located?" (e.g., "What country/state are you in?")
           - Extract: caller_location
           - STOP and wait for answer. Everything below depends on this.
           
           STEP 3: CONDITIONAL LOCATION-BASED QUESTIONS (choose based on their location)
           
           IF US CALLER (said "United States", "USA", "US", or a US state):
             a. Ask: "Which state are you in?" (if not already mentioned)
                Extract: caller_state
             b. Ask: "What's your current work authorization status? Are you a US Citizen, Green Card holder, on H1B, or would you need sponsorship?"
                Extract: visa_status (e.g., "US Citizen", "Green Card", "H1B", "Need sponsorship")
             c. Ask: "Do you need visa sponsorship to work in the US?"
                Extract: visa_sponsorship (e.g., "Yes", "No", "Already have visa")
           
           IF NOT US (International caller):
             Ask: "We have nearshore opportunities (remote work from your location) or you could need visa sponsorship to work in the US. Are you open to nearshore/remote work, or would you prefer US visa sponsorship, or both?"
             Extract: visa_sponsorship_preference (e.g., "Open to nearshore", "Need US visa sponsorship", "Both options")
           
           STEP 4: Relocation Check (only if their location doesn't match job locations)
           - Ask: "Our jobs are located in {available_jobs}. Are you willing to relocate if your location doesn't match?"
           - Extract: relocation_willing (e.g., "Yes", "No", "Maybe")
           
           - CRITICAL: Once all required details are collected, you MUST say: "I am sending a text message with a link for you to upload your resume and connecting you with our recruiter for the next steps."
           - NEVER ask for email address, phone number, or any other contact information. The system handles everything via SMS.
           - After confirming all details are collected, set "action": "forward" immediately.
           - DO NOT ask for email, phone, name, or personal contact info under any circumstances.

        2. US_STAFFING (Company looking to hire talent or build products)
           - GOAL: Collect 3 details: Roles they are hiring for, Tech stack needed, Preference for nearshore vs US-based.
           - Once all 3 are collected, set "action": "forward".

        3. GENERAL_INQUIRY (Questions about the company, hours, location)
           - GOAL: Answer their questions using ONLY the Knowledge Base.
           - Keep answering until they are satisfied. 
           - Set "action": "forward" ONLY if they explicitly ask to speak to a human.

        ENTITY EXTRACTION (JOB_SEEKER - COMPLETE LIST):
        - "role_interest": Job title or role they want (e.g., "Python Developer", "Data Engineer")
        - "tech_stack": Technologies they know or want to work with (e.g., "Python, React, AWS")
        - "experience_years": Years of professional experience (e.g., "3", "5+", "10 years")
        - "caller_location": Country or general location (e.g., "United States", "India", "Mexico")
        - "caller_state": (US ONLY) Which state they're in (e.g., "California", "New York")
        - "visa_status": (US ONLY) Work authorization status (e.g., "US Citizen", "Green Card", "H1B", "Need sponsorship")
        - "visa_sponsorship": (US ONLY) Do they need sponsorship? (e.g., "Yes", "No", "Already have visa")
        - "visa_sponsorship_preference": (INTERNATIONAL ONLY) Their preference (e.g., "Nearshore remote", "US visa sponsorship", "Both")
        - "relocation_willing": (CONDITIONAL) Only if their location doesn't match job locations (e.g., "Yes", "No", "Open to it")
        
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
        
        ⚠️ MANDATORY JSON OUTPUT FORMAT ⚠️
        Your response MUST ALWAYS be ONLY a valid JSON object. Nothing else.
        - Do NOT include markdown code blocks (no ```)
        - Do NOT include any explanatory text before or after the JSON
        - Do NOT apologize or use conversational language
        - Your ENTIRE response must be valid JSON that can be parsed by Python's json.loads()
        
        CORRECT FORMAT:
        {{"intent": "JOB_SEEKER", "confidence": 0.95, "entities": {{"role_interest": "Python Developer"}}, "reply_text": "Great! What technologies do you work with?", "action": "speak"}}
        
        WRONG FORMATS (DO NOT DO THESE):
        ❌ I'll respond with... (explanatory text)
        ❌ ```json\n{{"intent": ...}} (code block)
        ❌ First, let me say... (conversational preamble)
        ❌ {{"entities": null}} (null values in entities - extract actual values from user input)
        
        If user input is unclear, still respond with JSON. For example:
        {{"intent": "JOB_SEEKER", "confidence": 0.5, "entities": {{}}, "reply_text": "I didn't catch that. Could you please repeat?", "action": "speak", "branch": "JOB_SEEKER"}}
        """

        prompt_map = {
            "JOB_SEEKER": job_seeker_prompt,
            "US_STAFFING": f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions handling US staffing calls only.

        CONTEXT:
        {user_context}
        {missing_fields_instruction}

        GOAL:
        Collect exactly these fields: hiring_role, tech_stack, location_preference (US-based or nearshore LatAm), timeline.
        Forward only when all 4 required fields are collected.
        When all required fields are collected, reply that you are connecting them to a staffing specialist and set action to "forward".
        Do not ask for contact info.
        Always set intent and branch to "US_STAFFING".

        {common_json_contract}
            """,
            "AI_CAREER_DEV": f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions handling AI career development calls only.

        CONTEXT:
        {user_context}
        {missing_fields_instruction}

        GOAL:
        Collect exactly these fields: current_background, ai_goal, experience_level.
        Forward only when all 3 required fields are collected.
        When all required fields are collected, reply that you are connecting them to a specialist and set action to "forward".
        Always set intent and branch to "AI_CAREER_DEV".

        {common_json_contract}
            """,
            "AI_SMALL_BIZ": f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions handling AI for small business calls only.

        CONTEXT:
        {user_context}
        {missing_fields_instruction}

        GOAL:
        Collect exactly these fields: business_type, pain_point, current_tools.
        Forward only when all 3 required fields are collected.
        When all required fields are collected, reply that you are connecting them to a specialist and set action to "forward".
        Always set intent and branch to "AI_SMALL_BIZ".

        {common_json_contract}
            """,
            "AI_PROD_DEV": f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions handling AI product development calls only.

        CONTEXT:
        {user_context}
        {missing_fields_instruction}

        GOAL:
        Collect exactly these fields: product_idea, target_user, timeline.
        budget_range is optional and must not gate forwarding.
        Forward only when product_idea, target_user, and timeline are all collected.
        When required fields are collected, reply that you are connecting them to a specialist and set action to "forward".
        Always set intent and branch to "AI_PROD_DEV".

        {common_json_contract}
            """,
            "GENERAL_INQUIRY": f"""
        You are the Voice AI Receptionist for Bhuvi IT Solutions handling general inquiries only.

        KNOWLEDGE BASE:
        {retrieved_knowledge}

        RULES:
        - Answer using only the knowledge base.
        - Keep action as "speak" unless the caller explicitly asks for a human.
        - If caller explicitly asks for a human representative, set action to "forward".
        - Always set intent and branch to "GENERAL_INQUIRY".

        {common_json_contract}
            """,
        }

        system_prompt = prompt_map.get(active_branch, prompt_map["GENERAL_INQUIRY"])

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
                
                saved_branch = exchange.get("branch", saved_intent)
                fake_json = f'{{"intent": "{saved_intent}", "confidence": 0.9, "entities": {entities_json}, "reply_text": "{safe_ai_text}", "action": "speak", "branch": "{saved_branch}"}}'
                chat_messages.append({"role": "assistant", "content": fake_json})
        
        chat_messages.append({"role": "user", "content": text})
        
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=600,  # Reduced to enforce brevity and prevent webhook timeouts
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
            
            normalized_content = raw_content.replace("\n", " ").replace("\r", " ").strip()
            data = self._extract_first_json_object(normalized_content)
            if data is None:
                # Claude returned text with no parseable JSON object — wrap it gracefully
                print(f"⚠️  Claude returned non-parseable JSON. Wrapping as {active_branch} speak turn.")
                return AIResponse(
                    intent=active_branch,
                    confidence=0.5,
                    reply_text=raw_content,
                    action="speak",
                    entities={},
                    branch=active_branch
                )

            response = AIResponse(**data)
            if not response.branch:
                response.branch = active_branch
            
            print(f"LLM Intent: {response.intent}")
            print(f"LLM Entities Extracted: {response.entities}")
            print(f"LLM Reply: {response.reply_text}")
            
            return response
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON Parse Error: {e}")
            print(f"❌ Claude returned non-JSON text. Raw response: {raw_content[:300]}")
            print(f"⚠️  System prompt may need adjustment - Claude is not following JSON-only instruction")
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
    
    async def generate_call_summary(self, intent: str, call_memory: list, profile_data: Optional[dict] = None) -> str:
        """
        Generate a concise call summary (whisper) for the recruiter/representative.
        This will be played to Subbu before connecting the call.
        
        Args:
            intent: The detected intent (JOB_SEEKER, US_STAFFING, etc.)
            call_memory: List of conversation exchanges
            profile_data: The final extracted profile with all entities
        """
        profile_data = profile_data or {}
        
        print(f"[CALL WHISPER DEBUG] Intent: {intent}")
        print(f"[CALL WHISPER DEBUG] Profile data received: {profile_data}")
        print(f"[CALL WHISPER DEBUG] Call memory exchanges: {len(call_memory)}")
        
        if not profile_data and not call_memory:
            return "No information collected from the call."
        
        # Build extracted details summary from profile - THIS IS THE PRIMARY SOURCE
        if intent == "JOB_SEEKER" and profile_data:
            role = profile_data.get("role_interest", "Unknown role")
            exp = profile_data.get("experience_years", "Unknown experience")
            tech = profile_data.get("tech_stack", "Unknown tech stack")
            location = profile_data.get("caller_location", "Unknown location")
            visa_pref = profile_data.get("visa_sponsorship_preference", "")
            visa_status = profile_data.get("visa_status", "")
            relocation = profile_data.get("relocation_willing", "")
            
            # Build the summary directly from the data (no LLM hallucination)
            work_pref = ""
            if visa_pref:
                work_pref = f", {visa_pref}"
            elif visa_status:
                work_pref = f", {visa_status}"
            if relocation:
                work_pref += f", {relocation}"
            
            summary = f"Candidate for {role} position. {exp} experience with {tech}. Located in {location}{work_pref}. Profile complete and ready for recruiter review."
            print(f"[CALL WHISPER] Generated: {summary}")
            return summary
        
        # Fallback for other intents or if profile is incomplete
        if not call_memory:
            return "No conversation history available."
        
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
        3. Include key details (role, years of experience, tech stack, visa status, etc.) if a JOB_SEEKER
        4. Include hiring needs and preferences if US_STAFFING
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