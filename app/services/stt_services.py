# app/services/stt_service.py
import os
from deepgram import DeepgramClient, PrerecordedOptions

class DeepgramSTT:
    def __init__(self):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            print("Error: DEEPGRAM_API_KEY is missing")
        self.client = DeepgramClient(self.api_key)

    async def transcribe(self, audio_url: str) -> str:
        """
        Sends the recording URL from Twilio to Deepgram.
        Returns the text.
        """
        try:
            # 1. Create the source object (URL)
            source = {"url": audio_url}

            # 2. Configure options (Fastest model, English)
            options = PrerecordedOptions(
                model="nova-2",
                smart_format=True,
                language="en"
            )

            # 3. Call Deepgram
            response = self.client.listen.prerecorded.v("1").transcribe_url(source, options) # type: ignore

            # 4. Extract text
            transcript = response.results.channels[0].alternatives[0].transcript
            return transcript

        except Exception as e:
            print(f"Deepgram Error: {e}")
            return ""