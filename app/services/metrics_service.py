"""
Metrics Service - Tracks call funnel, intent classification, profile completion, and system health
"""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

class MetricsService:
    """
    In-memory metrics tracker for voice call system.
    Tracks call progression, intent distribution, profile completion, and errors.
    """
    
    def __init__(self):
        # Call-level metrics
        self.calls = {}  # call_sid -> call metrics dict
        
        # Aggregated metrics (for dashboard)
        self.intent_distribution = defaultdict(int)  # intent -> count
        self.intent_confidence_sum = defaultdict(float)  # intent -> sum of confidences
        self.intent_confidence_count = defaultdict(int)  # intent -> count
        
        self.entities_extracted = defaultdict(lambda: defaultdict(int))  # intent -> field -> count
        self.entities_missing = defaultdict(lambda: defaultdict(int))  # intent -> field -> count
        
        self.error_counts = defaultdict(int)  # error_type -> count
        self.stt_success = 0
        self.stt_total = 0
        self.silent_turns = 0
        
        self.actions = defaultdict(int)  # action -> count (speak, forward, listen, etc.)
        self.repeat_callers = 0
        self.unique_callers = set()
        
        self.latencies = defaultdict(list)  # operation -> [times in ms]
        
        # Call state for tracking repeat callers
        self.caller_first_appearance = {}  # phone -> first timestamp
        self.caller_intent_history = defaultdict(list)  # phone -> [intents]
    
    def start_call(self, call_sid: str, phone_number: str) -> None:
        """Track a new call"""
        self.calls[call_sid] = {
            "call_sid": call_sid,
            "phone_number": phone_number,
            "start_time": datetime.now(),
            "turns": 0,
            "intents": [],
            "entities_extracted": {},
            "errors": [],
            "final_action": None,
            "completed": False
        }
        
        # Track unique callers and repeats
        if phone_number not in self.unique_callers:
            self.unique_callers.add(phone_number)
            self.caller_first_appearance[phone_number] = datetime.now()
        else:
            self.repeat_callers += 1
            self.caller_intent_history[phone_number].clear()  # reset intent history for new call
    
    def record_turn(self, call_sid: str, user_text: str, intent: str, confidence: float, entities: Dict[str, Any]) -> None:
        """Record a conversation turn"""
        if call_sid not in self.calls:
            return
        
        call = self.calls[call_sid]
        call["turns"] += 1
        call["intents"].append(intent)
        call["entities_extracted"].update(entities)
        
        # Track intent distribution
        self.intent_distribution[intent] += 1
        self.intent_confidence_sum[intent] += confidence
        self.intent_confidence_count[intent] += 1
        
        # Track which entities were extracted for this intent
        for key, value in entities.items():
            if value is not None and (not isinstance(value, str) or value.strip()):
                self.entities_extracted[intent][key] += 1
        
        # Track caller's intent history
        phone = call["phone_number"]
        if intent not in self.caller_intent_history[phone]:
            self.caller_intent_history[phone].append(intent)
    
    def record_stt_attempt(self, call_sid: str, success: bool, text: Optional[str] = None) -> None:
        """Track Speech-to-Text success"""
        self.stt_total += 1
        if success:
            self.stt_success += 1
        else:
            if call_sid in self.calls:
                self.calls[call_sid]["errors"].append("STT_FAILED")
                if not text or not text.strip():
                    self.silent_turns += 1
    
    def record_error(self, call_sid: str, error_type: str, error_msg: str = "") -> None:
        """Track an error during call processing"""
        self.error_counts[error_type] += 1
        if call_sid in self.calls:
            self.calls[call_sid]["errors"].append(error_type)
            logger.error(f"[{call_sid}] Error {error_type}: {error_msg}")
    
    def record_action(self, call_sid: str, action: str) -> None:
        """Track final action (forward, listen, speak)"""
        self.actions[action] += 1
        if call_sid in self.calls:
            self.calls[call_sid]["final_action"] = action
            if action == "forward":
                self.calls[call_sid]["completed"] = True
    
    def record_latency(self, operation: str, duration_ms: float) -> None:
        """Track operation latency (LLM, STT, Firestore, etc.)"""
        self.latencies[operation].append(duration_ms)
    
    def check_profile_completion(self, intent: str, profile_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluate how complete a profile is for a given intent.
        Returns completion metrics.
        """
        intent_requirements = {
            "JOB_SEEKER": [
                "role_interest", "tech_stack", "experience_years", 
                "caller_location", "caller_state", "visa_status", 
                "visa_sponsorship", "relocation_willing"
            ],
            "CLIENT_LEAD": [
                "company_name", "roles_hiring", "tech_stack", 
                "nearshore_preference", "hiring_timeline"
            ]
        }
        
        if intent not in intent_requirements:
            return {"complete": True, "filled": 0, "required": 0, "completion_pct": 0}
        
        required_fields = intent_requirements[intent]
        profile_data = profile_data or {}
        
        filled = sum(
            1 for field in required_fields 
            if field in profile_data and profile_data[field]
        )
        
        completion_pct = int((filled / len(required_fields) * 100)) if required_fields else 0
        
        # Track missing fields
        for field in required_fields:
            if field not in profile_data or not profile_data[field]:
                self.entities_missing[intent][field] += 1
        
        return {
            "intent": intent,
            "filled": filled,
            "required": len(required_fields),
            "completion_pct": completion_pct,
            "complete": filled == len(required_fields)
        }
    
    def get_call_summary(self, call_sid: str) -> Optional[Dict[str, Any]]:
        """Get summary for a single call"""
        if call_sid not in self.calls:
            return None
        
        call = self.calls[call_sid]
        duration = (datetime.now() - call["start_time"]).total_seconds()
        
        return {
            "call_sid": call_sid,
            "phone_number": call["phone_number"],
            "duration_seconds": duration,
            "turns": call["turns"],
            "intents": call["intents"],
            "primary_intent": call["intents"][-1] if call["intents"] else "UNKNOWN",
            "entities_extracted": call["entities_extracted"],
            "errors": call["errors"],
            "error_count": len(call["errors"]),
            "final_action": call["final_action"],
            "completed": call["completed"]
        }
    
    def get_aggregated_metrics(self) -> Dict[str, Any]:
        """Get system-wide aggregated metrics for dashboard"""
        avg_latencies = {}
        for op, times in self.latencies.items():
            if times:
                avg_latencies[op] = {
                    "avg_ms": sum(times) / len(times),
                    "min_ms": min(times),
                    "max_ms": max(times),
                    "samples": len(times)
                }
        
        intent_stats = {}
        for intent in self.intent_distribution.keys():
            count = self.intent_distribution[intent]
            conf_sum = self.intent_confidence_sum[intent]
            conf_count = self.intent_confidence_count[intent]
            avg_confidence = conf_sum / conf_count if conf_count > 0 else 0
            
            intent_stats[intent] = {
                "count": count,
                "avg_confidence": round(avg_confidence, 3),
                "fields_extracted": dict(self.entities_extracted[intent]),
                "fields_missing": dict(self.entities_missing[intent])
            }
        
        total_calls = len(self.calls)
        completed_calls = sum(1 for c in self.calls.values() if c["completed"])
        
        return {
            "timestamp": datetime.now().isoformat(),
            "call_funnel": {
                "total_started": total_calls,
                "completed": completed_calls,
                "completion_rate_pct": int((completed_calls / total_calls * 100)) if total_calls > 0 else 0,
                "abandoned": total_calls - completed_calls,
            },
            "intent_distribution": intent_stats,
            "transcription": {
                "stt_success_rate_pct": int((self.stt_success / self.stt_total * 100)) if self.stt_total > 0 else 0,
                "stt_total_attempts": self.stt_total,
                "stt_successful": self.stt_success,
                "silent_turns": self.silent_turns
            },
            "errors": {
                "total": sum(self.error_counts.values()),
                "by_type": dict(self.error_counts)
            },
            "user_behavior": {
                "unique_callers": len(self.unique_callers),
                "repeat_caller_events": self.repeat_callers,
                "avg_turns_per_call": int(sum(c["turns"] for c in self.calls.values()) / total_calls) if total_calls > 0 else 0,
                "avg_call_duration_seconds": int(sum((datetime.now() - c["start_time"]).total_seconds() for c in self.calls.values()) / total_calls) if total_calls > 0 else 0
            },
            "actions": {
                "speak": self.actions.get("speak", 0),
                "forward": self.actions.get("forward", 0),
                "listen": self.actions.get("listen", 0),
                "error": self.actions.get("error", 0)
            },
            "latencies": avg_latencies
        }
    
    def get_dashbaord_json(self) -> str:
        """Get metrics as JSON for dashboard endpoint"""
        metrics = self.get_aggregated_metrics()
        return json.dumps(metrics, indent=2)
    
    def log_metrics_summary(self) -> None:
        """Log a human-readable summary of metrics"""
        metrics = self.get_aggregated_metrics()
        
        logger.info("=" * 60)
        logger.info("METRICS SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Calls: {metrics['call_funnel']['total_started']} started, " +
                   f"{metrics['call_funnel']['completed']} completed " +
                   f"({metrics['call_funnel']['completion_rate_pct']}%)")
        logger.info(f"Users: {metrics['user_behavior']['unique_callers']} unique, " +
                   f"{metrics['user_behavior']['repeat_caller_events']} repeat visits")
        logger.info(f"STT Success: {metrics['transcription']['stt_success_rate_pct']}% " +
                   f"({metrics['transcription']['stt_successful']}/{metrics['transcription']['stt_total_attempts']})")
        logger.info(f"Errors: {metrics['errors']['total']} total")
        if metrics['latencies']:
            llm_latency = metrics['latencies'].get('llm_analyze', {}).get('avg_ms', 'N/A')
            logger.info(f"LLM Latency: {llm_latency}ms avg")
        logger.info("Intent Distribution:")
        for intent, stats in metrics['intent_distribution'].items():
            logger.info(f"  {intent}: {stats['count']} calls, {stats['avg_confidence']} avg confidence")
        logger.info("=" * 60)
