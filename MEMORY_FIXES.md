# Memory & State-Tracking System Fixes

## Overview
This document describes the fixes applied to resolve four critical logical flaws in the voice agent's memory and state-tracking system.

---

## 1. ✅ Fixed: Amnesia Greeting

### Problem
The system always answered the phone with a hardcoded, generic "new caller" script, never checking if the caller had an existing profile.

### Solution
**File:** [app/main.py](app/main.py) - `/voice` endpoint

- Added profile lookup **before** the first greeting
- Implemented personalized "Welcome back" messages for returning callers
- Greeting now references previously discussed roles (e.g., "I remember you were interested in Software Engineer positions")
- New callers still receive the generic introduction

### Example Behavior
```
First-time caller: "Hello! Thank you for calling Bhuvi IT Solutions..."
Returning caller: "Welcome back to Bhuvi IT Solutions! I remember you were interested in Software Engineer positions. How can I help you today?"
```

---

## 2. ✅ Fixed: Shallow Data Saving (No Entities)

### Problem
The system only saved top-level intent (e.g., `JOB_SEEKER`) to the database. Actual conversational details like "Software Engineer", "F-1 OPT", or "2 years experience" were never extracted or saved.

### Solution
**Files Modified:**
- [app/schemas.py](app/schemas.py) - Changed `entities` from `List[str]` to `Dict[str, str]`
- [app/services/llm_service.py](app/services/llm_service.py) - Updated prompt to extract structured entities
- [app/main.py](app/main.py) - Added entity extraction and persistence logic

### Extracted Entities
The system now extracts and saves:

**For Job Seekers:**
- `role_interest`: "Software Engineer", "UX Designer", etc.
- `tech_stack`: "Python, React, AWS", "Java, Spring Boot", etc.
- `experience_years`: "2", "5+", "Senior level", etc.
- `visa_status`: "F1 OPT", "H1B", "US Citizen", "Needs sponsorship", etc.
- `relocation_willing`: "Yes", "No", "Remote only", etc.

**For Clients:**
- `hiring_roles`: Comma-separated roles they're hiring for
- `hiring_preference`: "Nearshore", "US-based", "Hybrid", etc.

### Database Structure
```json
{
  "last_intent": "JOB_SEEKER",
  "last_interaction": "2026-02-23T14:30:00",
  "role_interest": "Software Engineer",
  "tech_stack": "Python, React, AWS",
  "experience_years": "3",
  "visa_status": "F1 OPT",
  "relocation_willing": "Yes"
}
```

---

## 3. ✅ Fixed: State Corruption on Error

### Problem
When the LLM failed (e.g., returning plain text instead of JSON), the system returned an `ERROR` intent as a fallback. However, it then blindly saved that ERROR intent to the database, destroying the user's previously saved profile data.

### Solution
**File:** [app/main.py](app/main.py) - `/transcribe` endpoint

Added a **guardrail** that prevents database updates when `intent == "ERROR"`:

```python
# GUARDRAIL: Do NOT save profile data if the LLM returned an ERROR intent
if ai_response_obj.intent != "ERROR":
    # ... save entities to database ...
else:
    print(f"[{call_sid}] GUARDRAIL: Skipping profile update due to ERROR intent")
```

### Behavior
- ✅ Normal responses: Profile is updated with new entities
- ❌ ERROR responses: Profile is preserved (no update)
- 📞 Call is still forwarded to a human representative

---

## 4. ✅ Fixed: Prompt Vulnerability ("Do you remember me?")

### Problem
When a user asked "Do you remember me?", the LLM broke its strict JSON output constraint and outputted a plain-text apology, triggering the ERROR state and potentially corrupting the profile.

### Solution
**File:** [app/services/llm_service.py](app/services/llm_service.py)

1. **Enhanced User Context**: The prompt now shows previously collected entities clearly:
   ```
   - RETURNING CALLER DETECTED: 
       Previously collected: Role: Software Engineer, Experience: 3 years, Visa: F1 OPT
   ```

2. **Strict JSON Override**: Added explicit instructions to **never break JSON format**, even when acknowledging memory:
   ```
   CRITICAL OUTPUT FORMAT (NEVER BREAK THIS):
   You MUST respond with ONLY a valid JSON object - EVEN if the user asks "do you remember me?" or similar questions.
   
   ABSOLUTE RULE: Do not add any explanation, markdown, apology, or other text outside the JSON object.
   Even if confused, uncertain, or asked about memory - ALWAYS output valid JSON.
   ```

3. **Natural Acknowledgment**: The LLM can now acknowledge past information **within the JSON `reply_text` field**:
   ```json
   {
     "intent": "JOB_SEEKER",
     "reply_text": "[EN] Yes, I remember you! You were looking for Software Engineer roles with Python and React experience. How can I help you today?",
     "action": "speak"
   }
   ```

---

## Testing Checklist

### Test Case 1: First-Time Caller
- [ ] Call the system for the first time
- [ ] Verify generic greeting is played
- [ ] Provide job details (role, experience, visa)
- [ ] Check Firestore for saved entities

### Test Case 2: Returning Caller
- [ ] Call again from the same number
- [ ] Verify personalized "Welcome back" greeting
- [ ] Confirm previously saved details are mentioned
- [ ] Verify system doesn't ask for already-collected info

### Test Case 3: Memory Question
- [ ] During call, ask "Do you remember me?"
- [ ] Verify system responds naturally with saved info
- [ ] Confirm response is valid JSON (check logs)
- [ ] Verify profile is NOT corrupted

### Test Case 4: Error Handling
- [ ] Trigger an error scenario (if possible)
- [ ] Verify call is forwarded to human
- [ ] Check Firestore to confirm profile was NOT overwritten with ERROR
- [ ] Previously saved entities should still be intact

---

## Database Schema (Firestore)

### Collection: `caller_profiles`
### Document ID: `{phone_number}` (e.g., "+14155551234")

```json
{
  "last_intent": "JOB_SEEKER",
  "last_interaction": "2026-02-23T14:30:00Z",
  "role_interest": "Software Engineer",
  "tech_stack": "Python, React, AWS",
  "experience_years": "3",
  "visa_status": "F1 OPT",
  "relocation_willing": "Yes"
}
```

---

## Benefits

1. **Personalized Experience**: Returning callers feel recognized and valued
2. **Data Persistence**: Valuable conversation details are now saved and retrievable
3. **Error Resilience**: Technical failures don't destroy user profiles
4. **Natural Conversations**: Users can ask about their history without breaking the system
5. **Reduced Friction**: System won't ask the same questions again on repeat calls

---

## Notes for Deployment

1. **Firestore Credentials**: Ensure `GOOGLE_APPLICATION_CREDENTIALS` is set in production
2. **Entity Validation**: Consider adding validation logic for entity values
3. **Privacy Compliance**: Document data retention policies for caller profiles
4. **Monitoring**: Add alerts for ERROR intent frequency to catch systemic issues
