from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ElevenLabsBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ElevenLabsAnalysis(ElevenLabsBaseModel):
    evaluation_criteria_results: Dict[str, Any] = Field(default_factory=dict)
    data_collection_results: Dict[str, Any] = Field(default_factory=dict)
    call_successful: Optional[str] = None
    transcript_summary: Optional[str] = None


class ElevenLabsConversationInitiationClientData(ElevenLabsBaseModel):
    dynamic_variables: Dict[str, Any] = Field(default_factory=dict)
    conversation_config_override: Optional[Dict[str, Any]] = None
    custom_llm_extra_body: Dict[str, Any] = Field(default_factory=dict)


class ElevenLabsConversationData(ElevenLabsBaseModel):
    agent_id: Optional[str] = None
    conversation_id: str
    status: Optional[str] = None
    transcript: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    analysis: ElevenLabsAnalysis = Field(default_factory=ElevenLabsAnalysis)
    conversation_initiation_client_data: ElevenLabsConversationInitiationClientData = (
        Field(default_factory=ElevenLabsConversationInitiationClientData)
    )


class ElevenLabsPostCallWebhook(ElevenLabsBaseModel):
    type: Literal["post_call_transcription"]
    event_timestamp: Optional[int] = None
    data: ElevenLabsConversationData


class InitiateCustomParameters(ElevenLabsBaseModel):
    caller_number: Optional[str] = None
    caller_id: Optional[str] = None
    caller_country: Optional[str] = None
    caller_state: Optional[str] = None
    caller_city: Optional[str] = None
    call_sid: Optional[str] = None


class InitiateConversationData(ElevenLabsBaseModel):
    custom_parameters: InitiateCustomParameters = Field(
        default_factory=InitiateCustomParameters
    )


class ElevenLabsInitiateRequest(ElevenLabsBaseModel):
    # Nested format sent by ElevenLabs webhook (Twilio Function path)
    conversation_initiation_client_data: Optional[InitiateConversationData] = None
    # Flat fallback fields
    caller_id: Optional[str] = None
    caller_number: Optional[str] = None
    agent_id: Optional[str] = None
    called_number: Optional[str] = None
    call_sid: Optional[str] = None


class ElevenLabsInitiateResponse(ElevenLabsBaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, exclude_none=True)
    type: Literal["conversation_initiation_client_data"] = (
        "conversation_initiation_client_data"
    )
    dynamic_variables: Dict[str, Any] = Field(default_factory=dict)
    conversation_config_override: Optional[Dict[str, Any]] = None
    custom_llm_extra_body: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    firestore: Literal["connected", "unavailable"]
