# app/interfaces.py
from abc import ABC, abstractmethod
from typing import AsyncGenerator

class STTProvider(ABC):
    """
    The 'Ears' interface for Speech-to-Text providers.
    Any service that turns Audio to Text must follow this rule.
    """
    @abstractmethod
    async def transcribe(self, audio_data: bytes) -> str:
        pass
    
class TTSProvider(ABC):
    """
    The 'Mouth' interface for Text-to-Speech providers.
    Any service that turns Text to Audio must follow this rule.
    """
    @abstractmethod
    async def synthesize(self, text: str) -> AsyncGenerator[bytes, None]:
        pass
    
class LLMProvider(ABC):
    """
    The 'Brain' interface for Large Language Model providers.
    Any service that processes Text and generates Text must follow this rule.
    """
    @abstractmethod
    async def analyze_call(self, text: str) -> str:
        pass