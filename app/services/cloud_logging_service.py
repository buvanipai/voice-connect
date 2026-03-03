"""
Cloud Logging Service - Integrates metrics with Google Cloud Logging
Sends structured logs to GCP for persistence, querying, and monitoring
"""
import json
import logging
from typing import Dict, Any, Optional
from google.cloud import logging as cloud_logging
from datetime import datetime

logger = logging.getLogger(__name__)

class CloudLoggingService:
    """
    Sends metrics and call events to Google Cloud Logging for persistence and analysis.
    Integrates with local MetricsService.
    """
    
    def __init__(self):
        try:
            # Initialize Google Cloud Logging client
            self.cloud_client = cloud_logging.Client()
            self.logger = self.cloud_client.logger("voice-connect-metrics")
            self.enabled = True
            logger.info("[Cloud Logging] Successfully initialized Google Cloud Logging")
        except Exception as e:
            logger.warning(f"[Cloud Logging] Failed to initialize: {e}. Logging will be local-only.")
            self.enabled = False
    
    def log_call_event(self, call_event: Dict[str, Any]) -> None:
        """
        Log a call event with structured data.
        Includes call metadata, intent, entities, errors, etc.
        """
        if not self.enabled:
            return
        
        try:
            self.logger.log_struct(
                {
                    "event_type": "call_event",
                    "timestamp": datetime.now().isoformat(),
                    **call_event
                },
                severity="INFO"
            )
        except Exception as e:
            logger.error(f"[Cloud Logging] Failed to log call event: {e}")
    
    def log_turn_event(self, call_sid: str, turn_number: int, turn_data: Dict[str, Any]) -> None:
        """
        Log a single conversation turn with intent, entities, confidence.
        """
        if not self.enabled:
            return
        
        try:
            self.logger.log_struct(
                {
                    "event_type": "turn_event",
                    "call_sid": call_sid,
                    "turn_number": turn_number,
                    "timestamp": datetime.now().isoformat(),
                    **turn_data
                },
                severity="INFO"
            )
        except Exception as e:
            logger.error(f"[Cloud Logging] Failed to log turn event: {e}")
    
    def log_error_event(self, call_sid: str, error_type: str, error_msg: str, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Log an error with error type, message, and optional context.
        """
        if not self.enabled:
            return
        
        try:
            log_data = {
                "event_type": "error_event",
                "call_sid": call_sid,
                "error_type": error_type,
                "error_message": error_msg,
                "timestamp": datetime.now().isoformat()
            }
            if context:
                log_data["context"] = context
            
            self.logger.log_struct(log_data, severity="ERROR")
        except Exception as e:
            logger.error(f"[Cloud Logging] Failed to log error event: {e}")
    
    def log_stt_metric(self, call_sid: str, success: bool, text: Optional[str] = None, duration_ms: float = 0) -> None:
        """
        Log Speech-to-Text attempt with success status and latency.
        """
        if not self.enabled:
            return
        
        try:
            self.logger.log_struct(
                {
                    "event_type": "stt_metric",
                    "call_sid": call_sid,
                    "success": success,
                    "text_length": len(text) if text else 0,
                    "duration_ms": duration_ms,
                    "timestamp": datetime.now().isoformat()
                },
                severity="INFO"
            )
        except Exception as e:
            logger.error(f"[Cloud Logging] Failed to log STT metric: {e}")
    
    def log_profile_completion(self, phone_number: str, intent: str, completion: Dict[str, Any]) -> None:
        """
        Log profile completion metrics for an intent.
        """
        if not self.enabled:
            return
        
        try:
            self.logger.log_struct(
                {
                    "event_type": "profile_completion",
                    "phone_number": phone_number,
                    "intent": intent,
                    "filled_fields": completion.get("filled", 0),
                    "required_fields": completion.get("required", 0),
                    "completion_pct": completion.get("completion_pct", 0),
                    "timestamp": datetime.now().isoformat()
                },
                severity="INFO"
            )
        except Exception as e:
            logger.error(f"[Cloud Logging] Failed to log profile completion: {e}")
    
    def log_aggregated_metrics(self, metrics: Dict[str, Any]) -> None:
        """
        Log aggregated system metrics from MetricsService.
        Called periodically or on-demand to persist dashboard data.
        """
        if not self.enabled:
            return
        
        try:
            self.logger.log_struct(
                {
                    "event_type": "aggregated_metrics",
                    "timestamp": datetime.now().isoformat(),
                    **metrics
                },
                severity="INFO"
            )
        except Exception as e:
            logger.error(f"[Cloud Logging] Failed to log aggregated metrics: {e}")
    
    def create_log_entry_dict(self, call_sid: str, **kwargs) -> Dict[str, Any]:
        """
        Helper to create a structured log entry dict.
        Useful for passing data around before logging.
        """
        return {
            "call_sid": call_sid,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
