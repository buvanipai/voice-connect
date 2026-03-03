import logging
from typing import Optional, Dict, Any, cast
from google.cloud import firestore
from google.cloud.firestore_v1.base_document import DocumentSnapshot

logger = logging.getLogger(__name__)

# Initialize the client globally so it connects once on startup
_firestore_client = None

def get_firestore_client():
    global _firestore_client
    if _firestore_client is None:
        try:
            _firestore_client = firestore.Client()
            logger.info("Firestore client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Firestore: {e}")
    return _firestore_client

class ProfileService:
    def __init__(self):
        self.db = get_firestore_client()
        if self.db:
            self.collection = self.db.collection("caller_profiles")
        else:
            self.collection = None

    def get_profile(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Synchronous method to get caller profile from Firestore"""
        if not self.collection: 
            return None
        try:
            doc = cast(DocumentSnapshot, self.collection.document(phone_number).get())
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Firestore Read Error: {e}")
            return None

    def update_profile(self, phone_number: str, data: dict) -> None:
        """Synchronous method to update caller profile in Firestore"""
        if not self.collection: 
            return
        try:
            self.collection.document(phone_number).set(data, merge=True)
        except Exception as e:
            logger.error(f"Firestore Write Error: {e}")

    def get_intent_entities(self, phone_number: str, intent: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve entities scoped to a specific intent.
        Returns intent-specific entities merged with shared root fields.
        """
        profile = self.get_profile(phone_number)
        if not profile:
            return None
        
        # Start with shared metadata
        shared = {
            k: v for k, v in profile.items() 
            if k in ["last_intent", "last_interaction", "created_at"]
        }
        
        # Merge intent-specific entities if they exist
        intents = profile.get("intents", {})
        intent_data = intents.get(intent, {})
        
        return {**shared, **intent_data}

    def update_profile_for_intent(self, phone_number: str, intent: str, entities: dict, shared_data: Optional[dict] = None) -> None:
        """
        Save entities scoped to a specific intent.
        Keeps intent-specific data separate while preserving other intents' data.
        
        Args:
            phone_number: Caller's phone
            intent: The intent name (JOB_SEEKER, CLIENT_LEAD, etc.)
            entities: Entity dict to save under intents[intent]
            shared_data: Optional dict of shared metadata (last_intent, last_interaction, etc.)
        """
        if not self.collection:
            return
        
        try:
            # Get current profile to preserve other intents
            current = self.get_profile(phone_number) or {}
            
            # Preserve intents structure, merge new entities for this intent
            intents = current.get("intents", {})
            intents[intent] = {
                **intents.get(intent, {}),  # Keep existing intent data
                **{k: v for k, v in entities.items() if v is not None and (not isinstance(v, str) or v.strip())}  # New entities
            }
            
            # Build update payload
            update = {"intents": intents}
            
            # Merge shared metadata if provided
            if shared_data:
                update.update(shared_data)
            
            self.collection.document(phone_number).set(update, merge=True)
        except Exception as e:
            logger.error(f"Firestore Write Error: {e}")