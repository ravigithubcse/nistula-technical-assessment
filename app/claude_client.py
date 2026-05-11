"""
Claude AI Client Module
Author: Ravikumar

Handles all interactions with the Anthropic Claude API for generating
guest message replies. Includes prompt engineering, context injection,
and structured output parsing.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

import anthropic
from anthropic import Anthropic

from app.config import get_settings
from app.schemas import AIResponse, QueryType

# =============================================================================
# LOGGER SETUP
# =============================================================================

logger = logging.getLogger(__name__)

# =============================================================================
# MOCK PROPERTY CONTEXT
# =============================================================================

# Property details injected into every Claude prompt
# Design Decision (Ravikumar):
# - Centralized property data ensures consistent responses
# - Easy to extend with multiple properties in future
# - Formatted for optimal AI comprehension

PROPERTY_CONTEXT = """
PROPERTY DETAILS (Villa B1):
============================
Name: Villa B1, Assagao, North Goa
Bedrooms: 3 | Max guests: 6 | Private pool: Yes
Check-in: 2:00 PM | Check-out: 11:00 AM
Base rate: INR 18,000 per night (up to 4 guests)
Extra guest: INR 2,000 per night per person (guests 5 and 6)
WiFi password: Nistula@2024
Caretaker: Available 8:00 AM to 10:00 PM
Chef on call: Yes, pre-booking required (additional charges apply)
Current Availability (April 20-24): Available
Cancellation Policy: Free cancellation up to 7 days before check-in
Security deposit: INR 10,000 (refundable within 5 business days after check-out)
Nearby attractions: Anjuna Beach (3km), Vagator Beach (4km), Saturday Night Market (2km)
Airport: Dabolim Airport (45km), MOPA Airport (25km)
"""

# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = f"""You are Nistula's AI Concierge - a friendly, helpful assistant for Villa B1 in Goa.
Your job is to draft replies to guest messages with accuracy and warmth.

{PROPERTY_CONTEXT}

CRITICAL INSTRUCTIONS:
1. ALWAYS use the property details above - never make up information
2. If you're unsure about something, say so and offer to connect them with a human agent
3. Be warm, professional, and use the guest's name when provided
4. For availability questions, check the dates mentioned against current availability
5. For pricing, calculate accurately based on guest count and nights
6. Keep responses concise but complete (3-5 sentences for simple queries)
7. If multiple questions are asked, address each one clearly
8. For complaints, acknowledge the issue, apologize sincerely, and offer immediate help
9. ALWAYS respond in the same language as the guest's message
10. Include relevant next steps (booking link, contact info, etc.)

CONFIDENCE SCORING GUIDE:
- Score 0.9-1.0: You have all info needed and the answer is straightforward
- Score 0.7-0.89: You can answer but some details might need verification
- Score 0.5-0.69: Partial answer possible, recommend human follow-up
- Score below 0.5: Cannot answer confidently, escalate to human agent

OUTPUT FORMAT (JSON):
You MUST respond with ONLY a valid JSON object in this exact format:
{{
    "drafted_reply": "Your complete reply text here...",
    "confidence_score": 0.92,
    "confidence_explanation": "Brief reason for this confidence score",
    "suggested_action": "auto_send",
    "key_points_addressed": ["Point 1 from guest message", "Point 2"]
}}

Valid actions: "auto_send", "agent_review", "escalate"
"""


# =============================================================================
# CLAUDE CLIENT CLASS
# =============================================================================

class ClaudeClient:
    """
    Client for interacting with the Anthropic Claude API.
    
    Design Decision (Ravikumar):
    - Singleton pattern ensures single API client instance
    - Structured JSON output parsing for reliable data extraction
    - Comprehensive error handling for API failures
    - Logging for debugging and monitoring
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize the Claude client.
        
        Args:
            api_key: Anthropic API key (falls back to settings if not provided)
            model: Claude model identifier (falls back to settings if not provided)
        """
        settings = get_settings()
        self.api_key = api_key or settings.claude_api_key
        self.model = model or settings.claude_model
        self.client: Optional[Anthropic] = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize the Anthropic API client."""
        try:
            self.client = Anthropic(api_key=self.api_key)
            logger.info(f"Claude client initialized with model: {self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize Claude client: {str(e)}")
            raise RuntimeError(f"Claude API client initialization failed: {str(e)}")
    
    def _build_user_prompt(
        self,
        guest_name: str,
        message_text: str,
        query_type: QueryType,
        booking_ref: Optional[str] = None
    ) -> str:
        """
        Build the user prompt with context for Claude.
        
        Design Decision (Ravikumar):
        - Structured prompt ensures consistent AI behavior
        - Includes all relevant context (guest info, query type, booking ref)
        - Clear instructions for JSON output
        
        Args:
            guest_name: Name of the guest
            message_text: The guest's message
            query_type: Classified query type
            booking_ref: Optional booking reference
            
        Returns:
            str: Formatted user prompt
        """
        prompt_parts = [
            f"Guest Name: {guest_name}",
            f"Query Type: {query_type.value}",
        ]
        
        if booking_ref:
            prompt_parts.append(f"Booking Reference: {booking_ref}")
        
        prompt_parts.extend([
            f"\nGuest Message:\n{message_text}",
            "\nPlease draft a reply and provide your confidence assessment in the required JSON format.",
        ])
        
        return "\n".join(prompt_parts)
    
    def _parse_ai_response(self, response_text: str) -> AIResponse:
        """
        Parse the AI response text into structured AIResponse.
        
        Design Decision (Ravikumar):
        - Handles JSON extraction from response (Claude sometimes wraps in markdown)
        - Validates all required fields are present
        - Provides fallback parsing for edge cases
        
        Args:
            response_text: Raw text response from Claude
            
        Returns:
            AIResponse: Structured response data
            
        Raises:
            ValueError: If response cannot be parsed
        """
        # Try to extract JSON from the response
        # Claude sometimes wraps JSON in markdown code blocks
        json_text = response_text.strip()
        
        # Remove markdown code block wrappers if present
        if json_text.startswith("```json"):
            json_text = json_text[7:]
        elif json_text.startswith("```"):
            json_text = json_text[3:]
        
        if json_text.endswith("```"):
            json_text = json_text[:-3]
        
        json_text = json_text.strip()
        
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Claude response: {str(e)}")
            logger.debug(f"Raw response: {response_text}")
            raise ValueError(f"Invalid JSON in Claude response: {str(e)}")
        
        # Validate required fields
        required_fields = ["drafted_reply", "confidence_score", "confidence_explanation"]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field in Claude response: {field}")
        
        # Extract and validate values
        drafted_reply = data["drafted_reply"].strip()
        if not drafted_reply:
            raise ValueError("Empty drafted_reply in Claude response")
        
        try:
            confidence_score = float(data["confidence_score"])
            confidence_score = max(0.0, min(1.0, confidence_score))
        except (ValueError, TypeError):
            confidence_score = 0.5  # Default to medium confidence
        
        confidence_explanation = data["confidence_explanation"].strip()
        if not confidence_explanation:
            confidence_explanation = "No explanation provided"
        
        # Parse suggested_action
        suggested_action_str = data.get("suggested_action", "agent_review").lower()
        from app.schemas import ActionType
        try:
            suggested_action = ActionType(suggested_action_str)
        except ValueError:
            # Map based on confidence
            if confidence_score >= 0.85:
                suggested_action = ActionType.AUTO_SEND
            elif confidence_score >= 0.60:
                suggested_action = ActionType.AGENT_REVIEW
            else:
                suggested_action = ActionType.ESCALATE
        
        # Parse key_points_addressed
        key_points = data.get("key_points_addressed", [])
        if isinstance(key_points, str):
            key_points = [key_points]
        elif not isinstance(key_points, list):
            key_points = []
        
        return AIResponse(
            drafted_reply=drafted_reply,
            confidence_score=confidence_score,
            confidence_explanation=confidence_explanation,
            suggested_action=suggested_action,
            key_points_addressed=key_points
        )
    
    def generate_reply(
        self,
        guest_name: str,
        message_text: str,
        query_type: QueryType,
        booking_ref: Optional[str] = None
    ) -> AIResponse:
        """
        Generate an AI reply for a guest message.
        
        This is the main entry point for AI response generation.
        
        Args:
            guest_name: Name of the guest
            message_text: The guest's message text
            query_type: Classified query type
            booking_ref: Optional booking reference
            
        Returns:
            AIResponse: Structured response with drafted reply and confidence
            
        Raises:
            RuntimeError: If API call fails after retries
        """
        if not self.client:
            raise RuntimeError("Claude client not initialized")
        
        user_prompt = self._build_user_prompt(
            guest_name=guest_name,
            message_text=message_text,
            query_type=query_type,
            booking_ref=booking_ref
        )
        
        logger.info(f"Generating reply for guest: {guest_name}, query_type: {query_type.value}")
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            # Extract text from response
            response_text = ""
            for block in response.content:
                if block.type == "text":
                    response_text += block.text
            
            logger.debug(f"Claude raw response: {response_text[:200]}...")
            
            # Parse the response
            ai_response = self._parse_ai_response(response_text)
            
            logger.info(
                f"Reply generated successfully - "
                f"confidence: {ai_response.confidence_score}, "
                f"action: {ai_response.suggested_action.value}"
            )
            
            return ai_response
            
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {str(e)}")
            raise RuntimeError(f"Claude API error: {str(e)}")
        except anthropic.AuthenticationError as e:
            logger.error(f"Claude API authentication failed: {str(e)}")
            raise RuntimeError("Claude API authentication failed. Check your API key.")
        except anthropic.RateLimitError as e:
            logger.error(f"Claude API rate limit exceeded: {str(e)}")
            raise RuntimeError("Claude API rate limit exceeded. Please try again later.")
        except Exception as e:
            logger.error(f"Unexpected error calling Claude API: {str(e)}")
            raise RuntimeError(f"Failed to generate AI reply: {str(e)}")


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_claude_client: ClaudeClient | None = None


def get_claude_client() -> ClaudeClient:
    """
    Get or create the singleton ClaudeClient instance.
    
    Design Decision (Ravikumar):
    - Single shared client avoids recreating API connection per request
    - Lazy initialization - only creates when first needed
    """
    global _claude_client
    if _claude_client is None:
        _claude_client = ClaudeClient()
    return _claude_client
