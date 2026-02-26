# app/services/stt_service.py
import os
import logging
from deepgram import DeepgramClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeepgramSTT:
    def __init__(self):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            logger.error("ERROR: DEEPGRAM_API_KEY is missing.")
            self.client = None
            return

        try:
            self.client = DeepgramClient()
        except Exception as e:
            logger.error(f"Failed to initialize Deepgram: {e}")
            self.client = None

    async def transcribe(self, audio_url: str) -> str:
        """
        Transcribes audio from a URL using Deepgram.
        Returns the transcript string or an empty string on failure.
        """
        if not self.client:
            return "Error: Deepgram client not initialized."

        try:
            response = self.client.listen.v1.media.transcribe_url(
                url=audio_url,
                model="nova-2-phonecall",
                smart_format=True,
                language="en-US"
            )

            results = getattr(response, "results", None)
            
            if not results:
                logger.warning("Deepgram response contained no results.")
                return ""

            # Check channels (Pylance worries this might be None)
            channels = getattr(results, "channels", [])
            if not channels or len(channels) == 0:
                logger.warning("Deepgram results contained no channels.")
                return ""

            # Check alternatives
            alternatives = getattr(channels[0], "alternatives", [])
            if not alternatives or len(alternatives) == 0:
                return ""

            # Check transcript
            transcript = getattr(alternatives[0], "transcript", "")
            
            # Ensure we return a string (even if transcript was somehow None)
            return str(transcript) if transcript else ""

        except Exception as e:
            logger.error(f"Deepgram Error: {e}")
            return ""