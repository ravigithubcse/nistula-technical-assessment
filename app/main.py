"""
Nistula Unified Messaging Platform - Main Application
Author: Ravikumar

FastAPI application providing the webhook endpoint for receiving guest messages
from multiple channels, processing them through AI, and returning drafted replies.

Architecture:
- POST /webhook/message - Main webhook endpoint for inbound messages
- POST /webhook/test    - Testing endpoint for development
- GET /health           - Health check endpoint
- GET /docs             - Auto-generated API documentation
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.classifier import get_classifier
from app.claude_client import get_claude_client
from app.config import get_settings
from app.confidence_scorer import get_scorer
from app.schemas import (
    ActionType,
    ErrorResponse,
    InboundMessageRequest,
    QueryType,
    UnifiedMessage,
    WebhookResponse,
)

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

def setup_logging() -> None:
    """
    Configure application logging.
    
    Design Decision (Ravikumar):
    - Structured logging for production environments
    - Different log levels per environment
    - Request ID tracking for end-to-end traceability
    """
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    # Create formatter with timestamp, level, and request context
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = []
    root_logger.addHandler(console_handler)
    
    # Set specific log levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)


# Setup logging on module load
setup_logging()
logger = logging.getLogger(__name__)


# =============================================================================
# LIFESPAN EVENT HANDLER
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler for startup/shutdown events.
    
    Design Decision (Ravikumar):
    - Validates critical configuration on startup
    - Initializes singleton services proactively
    - Provides clear error messages if setup fails
    """
    logger.info("=" * 60)
    logger.info("Nistula Messaging Platform - Starting up")
    logger.info("=" * 60)
    
    try:
        # Validate configuration
        settings = get_settings()
        logger.info(f"Environment: {settings.environment}")
        logger.info(f"Claude Model: {settings.claude_model}")
        
        # Pre-initialize singletons to catch config errors early
        get_classifier()
        get_scorer()
        get_claude_client()
        
        logger.info("All services initialized successfully")
        
    except Exception as e:
        logger.error(f"Startup failed: {str(e)}")
        raise
    
    yield  # Application runs here
    
    logger.info("Nistula Messaging Platform - Shutting down")


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

def create_app() -> FastAPI:
    """
    Application factory - creates and configures the FastAPI app.
    
    Design Decision (Ravikumar):
    - Factory pattern allows easier testing with different configurations
    - All middleware and routes are registered here
    - CORS enabled for potential frontend integration
    """
    app = FastAPI(
        title="Nistula Unified Messaging Platform",
        description="Guest Message Handler - Receives messages from multiple channels, "
                    "processes with AI, and returns drafted replies with confidence scoring.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    
    # CORS middleware - allow all origins for webhook accessibility
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    return app


app = create_app()


# =============================================================================
# EXCEPTION HANDLERS
# =============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler for unhandled errors.
    
    Design Decision (Ravikumar):
    - Prevents stack traces from leaking to clients
    - Logs full error details server-side
    - Returns consistent error format
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])
    logger.error(f"Unhandled exception [req:{request_id}]: {str(exc)}", exc_info=True)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "An internal error occurred",
            "error_code": "INTERNAL_ERROR",
            "detail": "Please try again or contact support",
            "request_id": request_id
        }
    )


# =============================================================================
# REQUEST MIDDLEWARE
# =============================================================================

@app.middleware("http")
async def add_request_metadata(request: Request, call_next):
    """
    Add request ID and timing metadata to every request.
    
    Design Decision (Ravikumar):
    - Request IDs enable log correlation across services
    - Timing data helps identify performance issues
    - Metadata is stored in request.state for access in route handlers
    """
    request.state.request_id = str(uuid.uuid4())[:12]
    request.state.start_time = time.time()
    
    response = await call_next(request)
    
    # Add timing header
    duration = time.time() - request.state.start_time
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Response-Time"] = f"{duration:.3f}s"
    
    return response


# =============================================================================
# HEALTH CHECK ENDPOINT
# =============================================================================

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for monitoring and load balancers.
    
    Returns:
        Simple status response indicating service is operational
    """
    return {
        "status": "healthy",
        "service": "nistula-messaging-platform",
        "version": "1.0.0"
    }


# =============================================================================
# MAIN WEBHOOK ENDPOINT
# =============================================================================

@app.post(
    "/webhook/message",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Message processed successfully", "model": WebhookResponse},
        400: {"description": "Invalid request payload", "model": ErrorResponse},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error", "model": ErrorResponse},
        503: {"description": "AI service unavailable", "model": ErrorResponse},
    },
    tags=["Webhook"],
    summary="Receive and process guest messages",
    description="Receives inbound guest messages from any supported channel, "
                "classifies the query, generates an AI reply, and returns it with confidence scoring."
)
async def receive_message(
    request: Request,
    payload: InboundMessageRequest
) -> WebhookResponse:
    """
    Main webhook endpoint for processing guest messages.
    
    Pipeline (Ravikumar):
    1. Receive and validate inbound payload
    2. Classify query type using keyword analysis
    3. Normalize into unified schema
    4. Send to Claude AI with property context
    5. Calculate composite confidence score
    6. Determine action (auto_send / agent_review / escalate)
    7. Return structured response
    
    Args:
        request: FastAPI request object (for request_id)
        payload: Validated inbound message payload
        
    Returns:
        WebhookResponse: Processed message with drafted reply and confidence score
        
    Raises:
        HTTPException: For various error conditions with appropriate status codes
    """
    request_id = request.state.request_id
    start_time = request.state.start_time
    
    logger.info(
        f"[req:{request_id}] Received message from {payload.source.value} "
        f"- Guest: {payload.guest_name}"
    )
    
    try:
        # =========================================================================
        # STEP 1: CLASSIFY QUERY TYPE
        # =========================================================================
        logger.info(f"[req:{request_id}] Classifying query...")
        
        classifier = get_classifier()
        query_type = classifier.classify(payload.message)
        classification_scores = classifier.get_classification_scores(payload.message)
        
        logger.info(
            f"[req:{request_id}] Query classified as: {query_type.value} "
            f"(scores: {classification_scores})"
        )
        
        # =========================================================================
        # STEP 2: NORMALIZE INTO UNIFIED SCHEMA
        # =========================================================================
        unified_message = UnifiedMessage.from_inbound_request(payload, query_type)
        
        logger.info(
            f"[req:{request_id}] Message normalized - ID: {unified_message.message_id}"
        )
        
        # =========================================================================
        # STEP 3: GENERATE AI REPLY
        # =========================================================================
        logger.info(f"[req:{request_id}] Generating AI reply...")
        
        claude_client = get_claude_client()
        ai_response = claude_client.generate_reply(
            guest_name=payload.guest_name,
            message_text=payload.message,
            query_type=query_type,
            booking_ref=payload.booking_ref
        )
        
        logger.info(
            f"[req:{request_id}] AI reply generated - "
            f"confidence: {ai_response.confidence_score}"
        )
        
        # =========================================================================
        # STEP 4: CALCULATE COMPOSITE CONFIDENCE SCORE
        # =========================================================================
        logger.info(f"[req:{request_id}] Calculating final confidence score...")
        
        scorer = get_scorer()
        final_score, confidence_factors, action = scorer.calculate_final_score(
            ai_self_assessment=ai_response.confidence_score,
            guest_message=payload.message,
            drafted_reply=ai_response.drafted_reply,
            key_points_addressed=ai_response.key_points_addressed,
            classification_scores=classification_scores,
            query_type=query_type,
            has_booking_ref=bool(payload.booking_ref)
        )
        
        logger.info(
            f"[req:{request_id}] Final score: {final_score}, Action: {action.value} "
            f"| Factors: {confidence_factors.to_dict()}"
        )
        
        # =========================================================================
        # STEP 5: BUILD RESPONSE
        # =========================================================================
        response = WebhookResponse(
            message_id=unified_message.message_id,
            query_type=query_type,
            drafted_reply=ai_response.drafted_reply,
            confidence_score=final_score,
            action=action
        )
        
        # Log completion
        duration = time.time() - start_time
        logger.info(
            f"[req:{request_id}] Request completed in {duration:.3f}s - "
            f"Action: {action.value}"
        )
        
        return response
        
    except HTTPException:
        # Re-raise HTTP exceptions (they're already proper responses)
        raise
    except RuntimeError as e:
        # AI service errors
        logger.error(f"[req:{request_id}] AI service error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except Exception as e:
        # Unexpected errors
        logger.error(f"[req:{request_id}] Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred processing your message"
        )


# =============================================================================
# TEST WEBHOOK ENDPOINT (For Development)
# =============================================================================

@app.post(
    "/webhook/test",
    response_model=WebhookResponse,
    tags=["Testing"],
    summary="Test endpoint for webhook (no AI call)",
    description="Returns a mock response without calling the Claude API. "
                "Useful for testing integration and response format."
)
async def test_webhook(payload: InboundMessageRequest) -> WebhookResponse:
    """
    Test endpoint that bypasses AI for faster testing.
    
    Returns a mock response to verify integration without API costs.
    """
    from uuid import uuid4
    
    classifier = get_classifier()
    query_type = classifier.classify(payload.message)
    
    # Generate a mock reply based on query type
    mock_replies = {
        QueryType.PRE_SALES_AVAILABILITY: 
            f"Hi {payload.guest_name}! Thank you for your interest in Villa B1. "
            f"I'd be happy to check availability for your requested dates. "
            f"Let me verify and get back to you shortly with pricing details.",
        QueryType.PRE_SALES_PRICING:
            f"Hi {payload.guest_name}! Thank you for inquiring about our rates. "
            f"Our base rate is INR 18,000 per night for up to 4 guests. "
            f"Let me calculate the exact cost for your stay and send it to you.",
        QueryType.POST_SALES_CHECKIN:
            f"Hi {payload.guest_name}! Welcome to Villa B1! "
            f"Check-in is at 2:00 PM and the WiFi password is Nistula@2024. "
            f"Our caretaker will be available from 8 AM to 10 PM for any assistance.",
        QueryType.SPECIAL_REQUEST:
            f"Hi {payload.guest_name}! Thank you for your request. "
            f"We'd be happy to help arrange that for you. "
            f"Let me check availability with our team and confirm shortly.",
        QueryType.COMPLAINT:
            f"Hi {payload.guest_name}, I sincerely apologize for the inconvenience. "
            f"I completely understand your frustration and this is absolutely not the experience we want for our guests. "
            f"I'm escalating this to our property manager immediately who will contact you within 30 minutes.",
        QueryType.GENERAL_ENQUIRY:
            f"Hi {payload.guest_name}! Thank you for reaching out. "
            f"That's a great question about Villa B1. "
            f"Let me get you the most accurate information and reply shortly.",
    }
    
    mock_reply = mock_replies.get(
        query_type,
        f"Hi {payload.guest_name}! Thank you for your message. "
        f"I've received your inquiry and will get back to you shortly."
    )
    
    # Determine action based on query type
    if query_type == QueryType.COMPLAINT:
        action = ActionType.ESCALATE
        confidence = 0.45
    elif query_type in [QueryType.PRE_SALES_AVAILABILITY, QueryType.PRE_SALES_PRICING]:
        action = ActionType.AGENT_REVIEW
        confidence = 0.72
    else:
        action = ActionType.AUTO_SEND
        confidence = 0.88
    
    return WebhookResponse(
        message_id=uuid4(),
        query_type=query_type,
        drafted_reply=mock_reply,
        confidence_score=confidence,
        action=action
    )


# =============================================================================
# APPLICATION ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    
    logger.info("Starting Uvicorn server...")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower()
    )
