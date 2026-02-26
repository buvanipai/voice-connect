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