"""
Pydantic Schemas - Request/Response Models
Author: Ravikumar

Defines all data models for the Nistula messaging platform.
Every inbound and outbound payload is validated for type safety and completeness.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# ENUMS - Query Types and Message Sources
# =============================================================================

class QueryType(str, Enum):
    """
    Classification of guest message intent.
    
    Design Decision (Ravikumar):
    - Using Enum instead of plain strings prevents invalid query types
    - Each value is self-documenting with a clear purpose
    - Easy to extend with new query types as business needs evolve
    """
    PRE_SALES_AVAILABILITY = "pre_sales_availability"
    PRE_SALES_PRICING = "pre_sales_pricing"
    POST_SALES_CHECKIN = "post_sales_checkin"
    SPECIAL_REQUEST = "special_request"
    COMPLAINT = "complaint"
    GENERAL_ENQUIRY = "general_enquiry"


class MessageSource(str, Enum):
    """
    Supported inbound message channels.
    
    Design Decision (Ravikumar):
    - Enum ensures only supported channels are accepted
    - Normalized lowercase values for consistency
    """
    WHATSAPP = "whatsapp"
    BOOKING_COM = "booking_com"
    AIRBNB = "airbnb"
    INSTAGRAM = "instagram"
    DIRECT = "direct"


class ActionType(str, Enum):
    """
    Action to take based on confidence score.
    
    Design Decision (Ravikumar):
    - auto_send: High confidence (>= 0.85), safe to send without human review
    - agent_review: Medium confidence (0.60-0.85), needs human approval
    - escalate: Low confidence (< 0.60) or complaint, requires immediate human attention
    """
    AUTO_SEND = "auto_send"
    AGENT_REVIEW = "agent_review"
    ESCALATE = "escalate"


# =============================================================================
# INBOUND REQUEST SCHEMA (Webhook Payload)
# =============================================================================

class InboundMessageRequest(BaseModel):
    """
    Incoming webhook payload from any supported channel.
    
    This is the raw payload received at /webhook/message.
    All fields are validated to ensure data integrity before processing.
    """
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "source": "whatsapp",
            "guest_name": "Rahul Sharma",
            "message": "Is the villa available from April 20 to 24? What is the rate for 2 adults?",
            "timestamp": "2026-05-05T10:30:00Z",
            "booking_ref": "NIS-2024-0891",
            "property_id": "villa-b1"
        }
    })
    
    source: MessageSource = Field(
        ...,
        description="Channel that received the message (whatsapp, booking_com, airbnb, instagram, direct)"
    )
    guest_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Full name of the guest sending the message"
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The actual message text from the guest"
    )
    timestamp: datetime = Field(
        ...,
        description="ISO 8601 timestamp when the message was sent (UTC)"
    )
    booking_ref: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Optional booking/reference number if guest has a reservation"
    )
    property_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Identifier for the property the message is about"
    )
    
    @field_validator("guest_name", "message")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        """Strip leading/trailing whitespace from text fields."""
        return value.strip() if value else value


# =============================================================================
# UNIFIED MESSAGE SCHEMA (Internal Normalized Format)
# =============================================================================

class UnifiedMessage(BaseModel):
    """
    Normalized message format used internally across all channels.
    
    Design Decision (Ravikumar):
    - Every inbound message, regardless of source, gets normalized into this schema
    - This creates a single consistent interface for downstream processing (AI, database, etc.)
    - message_id is auto-generated UUID for traceability
    - query_type is determined by the classification module
    """
    model_config = ConfigDict(from_attributes=True)
    
    message_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this message (auto-generated)"
    )
    source: MessageSource = Field(
        ...,
        description="Channel that received the message"
    )
    guest_name: str = Field(
        ...,
        description="Full name of the guest"
    )
    message_text: str = Field(
        ...,
        description="The message content"
    )
    timestamp: datetime = Field(
        ...,
        description="When the message was sent (UTC)"
    )
    booking_ref: Optional[str] = Field(
        default=None,
        description="Booking reference if available"
    )
    property_id: str = Field(
        ...,
        description="Property identifier"
    )
    query_type: QueryType = Field(
        ...,
        description="AI-classified query category"
    )
    
    @classmethod
    def from_inbound_request(
        cls,
        request: InboundMessageRequest,
        query_type: QueryType
    ) -> "UnifiedMessage":
        """
        Factory method to create UnifiedMessage from inbound request.
        
        Args:
            request: The validated inbound webhook payload
            query_type: The classified query type
            
        Returns:
            UnifiedMessage: Normalized message ready for AI processing
        """
        return cls(
            source=request.source,
            guest_name=request.guest_name,
            message_text=request.message,
            timestamp=request.timestamp,
            booking_ref=request.booking_ref,
            property_id=request.property_id,
            query_type=query_type
        )


# =============================================================================
# AI RESPONSE SCHEMA (Claude API Output)
# =============================================================================

class AIResponse(BaseModel):
    """
    Structured output from the Claude AI model.
    
    Design Decision (Ravikumar):
    - Separates the AI-generated content from metadata
    - confidence_explanation provides transparency for scoring decisions
    - suggested_action helps with automated routing
    """
    model_config = ConfigDict(from_attributes=True)
    
    drafted_reply: str = Field(
        ...,
        description="The AI-generated response to send to the guest"
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="AI's confidence in the accuracy of the reply (0.0 to 1.0)"
    )
    confidence_explanation: str = Field(
        ...,
        description="Brief explanation of why this confidence score was assigned"
    )
    suggested_action: ActionType = Field(
        ...,
        description="Recommended action based on confidence"
    )
    key_points_addressed: list[str] = Field(
        default_factory=list,
        description="List of specific points from the guest message that were addressed"
    )


# =============================================================================
# WEBHOOK RESPONSE SCHEMA (Final API Output)
# =============================================================================

class WebhookResponse(BaseModel):
    """
    Final response returned by the /webhook/message endpoint.
    
    Design Decision (Ravikumar):
    - Includes message_id for traceability and correlation
    - query_type helps downstream analytics
    - action field enables automated workflow routing
    - Full transparency with confidence scoring
    """
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "message_id": "550e8400-e29b-41d4-a716-446655440000",
            "query_type": "pre_sales_availability",
            "drafted_reply": "Hi Rahul! Great news - Villa B1 is available...",
            "confidence_score": 0.91,
            "action": "auto_send"
        }
    })
    
    message_id: UUID = Field(
        ...,
        description="Unique identifier for this message (same as in unified schema)"
    )
    query_type: QueryType = Field(
        ...,
        description="Classified query type"
    )
    drafted_reply: str = Field(
        ...,
        description="AI-generated reply to send to the guest"
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Final confidence score (0.0 to 1.0)"
    )
    action: ActionType = Field(
        ...,
        description="Determined action: auto_send, agent_review, or escalate"
    )


# =============================================================================
# ERROR RESPONSE SCHEMA
# =============================================================================

class ErrorResponse(BaseModel):
    """
    Standardized error response for all API errors.
    
    Design Decision (Ravikumar):
    - Consistent error format makes client-side error handling easier
    - Includes error_code for programmatic error identification
    - request_id helps with debugging and log correlation
    """
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "error": "Invalid source channel",
            "error_code": "INVALID_SOURCE",
            "detail": "Source 'telegram' is not supported. Valid sources: whatsapp, booking_com, airbnb, instagram, direct",
            "request_id": "req_550e8400-e29b-41d4"
        }
    })
    
    error: str = Field(..., description="Human-readable error message")
    error_code: str = Field(..., description="Machine-readable error code")
    detail: Optional[str] = Field(default=None, description="Additional error context")
    request_id: str = Field(..., description="Unique request ID for log correlation")
