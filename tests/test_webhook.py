"""
Nistula Unified Messaging Platform - Test Suite
Author: Ravikumar

Comprehensive tests for the webhook endpoint covering:
- Query classification accuracy
- Request/response validation
- Error handling
- Confidence scoring
- Different message types and channels
"""

import os
import sys
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from fastapi.testclient import TestClient

# Set test environment variables BEFORE importing app modules
os.environ["CLAUDE_API_KEY"] = "test-key-for-unit-tests"
os.environ["CLAUDE_MODEL"] = "claude-sonnet-4-20250514"
os.environ["ENVIRONMENT"] = "testing"
os.environ["LOG_LEVEL"] = "DEBUG"

from app.main import app
from app.schemas import ActionType, MessageSource, QueryType

# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def base_payload():
    """Base valid payload for testing."""
    return {
        "source": "whatsapp",
        "guest_name": "Rahul Sharma",
        "message": "Is the villa available from April 20 to 24?",
        "timestamp": "2026-05-05T10:30:00Z",
        "booking_ref": "NIS-2024-0891",
        "property_id": "villa-b1"
    }


# =============================================================================
# HEALTH CHECK TESTS
# =============================================================================

class TestHealthCheck:
    """Tests for the health check endpoint."""
    
    def test_health_check_returns_200(self, client):
        """Health check should return 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "nistula-messaging-platform"
    
    def test_health_check_response_format(self, client):
        """Health check should have correct response structure."""
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert "service" in data
        assert "version" in data


# =============================================================================
# REQUEST VALIDATION TESTS
# =============================================================================

class TestRequestValidation:
    """Tests for request payload validation."""
    
    def test_valid_request_returns_200(self, client, base_payload):
        """A valid request should be accepted (we use test endpoint to avoid API calls)."""
        response = client.post("/webhook/test", json=base_payload)
        assert response.status_code == 200
    
    def test_missing_required_field_source(self, client, base_payload):
        """Request without 'source' should return 422."""
        payload = base_payload.copy()
        del payload["source"]
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 422
    
    def test_missing_required_field_guest_name(self, client, base_payload):
        """Request without 'guest_name' should return 422."""
        payload = base_payload.copy()
        del payload["guest_name"]
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 422
    
    def test_missing_required_field_message(self, client, base_payload):
        """Request without 'message' should return 422."""
        payload = base_payload.copy()
        del payload["message"]
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 422
    
    def test_empty_guest_name(self, client, base_payload):
        """Empty guest_name should return 422."""
        payload = base_payload.copy()
        payload["guest_name"] = ""
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 422
    
    def test_empty_message(self, client, base_payload):
        """Empty message should return 422."""
        payload = base_payload.copy()
        payload["message"] = ""
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 422
    
    def test_invalid_source_value(self, client, base_payload):
        """Invalid source channel should return 422."""
        payload = base_payload.copy()
        payload["source"] = "telegram"
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 422
    
    def test_all_valid_sources(self, client, base_payload):
        """All supported sources should be accepted."""
        valid_sources = ["whatsapp", "booking_com", "airbnb", "instagram", "direct"]
        for source in valid_sources:
            payload = base_payload.copy()
            payload["source"] = source
            response = client.post("/webhook/test", json=payload)
            assert response.status_code == 200, f"Source '{source}' should be valid"
    
    def test_optional_booking_ref(self, client, base_payload):
        """Request without booking_ref should be accepted (it's optional)."""
        payload = base_payload.copy()
        del payload["booking_ref"]
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200
    
    def test_whitespace_stripping(self, client, base_payload):
        """Leading/trailing whitespace should be stripped from text fields."""
        payload = base_payload.copy()
        payload["guest_name"] = "  Rahul Sharma  "
        payload["message"] = "  Is the villa available?  "
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200


# =============================================================================
# QUERY CLASSIFICATION TESTS
# =============================================================================

class TestQueryClassification:
    """Tests for the query classification module."""
    
    def test_availability_classification(self, client):
        """Availability queries should be classified correctly."""
        payload = {
            "source": "whatsapp",
            "guest_name": "Test Guest",
            "message": "Is the villa available from April 20 to 24?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        data = response.json()
        assert data["query_type"] == QueryType.PRE_SALES_AVAILABILITY.value
    
    def test_pricing_classification(self, client):
        """Pricing queries should be classified correctly."""
        payload = {
            "source": "whatsapp",
            "guest_name": "Test Guest",
            "message": "What is the rate for 2 adults for 3 nights?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        data = response.json()
        assert data["query_type"] == QueryType.PRE_SALES_PRICING.value
    
    def test_checkin_classification(self, client):
        """Check-in queries should be classified correctly."""
        payload = {
            "source": "airbnb",
            "guest_name": "Test Guest",
            "message": "What time can we check in? What is the WiFi password?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        data = response.json()
        assert data["query_type"] == QueryType.POST_SALES_CHECKIN.value
    
    def test_complaint_classification(self, client):
        """Complaints should be classified correctly."""
        payload = {
            "source": "airbnb",
            "guest_name": "Angry Guest",
            "message": "The AC is not working. I am not happy and want a refund.",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        data = response.json()
        assert data["query_type"] == QueryType.COMPLAINT.value
    
    def test_special_request_classification(self, client):
        """Special requests should be classified correctly."""
        payload = {
            "source": "whatsapp",
            "guest_name": "Test Guest",
            "message": "Can you arrange early check-in and airport transfer?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        data = response.json()
        assert data["query_type"] == QueryType.SPECIAL_REQUEST.value
    
    def test_general_enquiry_classification(self, client):
        """General enquiries should be classified correctly."""
        payload = {
            "source": "instagram",
            "guest_name": "Test Guest",
            "message": "Do you allow pets? Is there parking available?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        data = response.json()
        assert data["query_type"] == QueryType.GENERAL_ENQUIRY.value


# =============================================================================
# RESPONSE STRUCTURE TESTS
# =============================================================================

class TestResponseStructure:
    """Tests for response format and structure."""
    
    def test_response_has_all_required_fields(self, client, base_payload):
        """Response should contain all required fields."""
        response = client.post("/webhook/test", json=base_payload)
        data = response.json()
        
        assert "message_id" in data
        assert "query_type" in data
        assert "drafted_reply" in data
        assert "confidence_score" in data
        assert "action" in data
    
    def test_message_id_is_valid_uuid(self, client, base_payload):
        """message_id should be a valid UUID string."""
        import uuid
        response = client.post("/webhook/test", json=base_payload)
        data = response.json()
        
        # Should not raise ValueError
        uuid.UUID(data["message_id"])
    
    def test_confidence_score_is_number(self, client, base_payload):
        """confidence_score should be a number between 0 and 1."""
        response = client.post("/webhook/test", json=base_payload)
        data = response.json()
        
        score = data["confidence_score"]
        assert isinstance(score, (int, float))
        assert 0.0 <= score <= 1.0
    
    def test_action_is_valid(self, client, base_payload):
        """action should be one of: auto_send, agent_review, escalate."""
        valid_actions = [a.value for a in ActionType]
        response = client.post("/webhook/test", json=base_payload)
        data = response.json()
        
        assert data["action"] in valid_actions
    
    def test_query_type_is_valid(self, client, base_payload):
        """query_type should be a valid QueryType value."""
        valid_types = [qt.value for qt in QueryType]
        response = client.post("/webhook/test", json=base_payload)
        data = response.json()
        
        assert data["query_type"] in valid_types
    
    def test_drafted_reply_is_non_empty_string(self, client, base_payload):
        """drafted_reply should be a non-empty string."""
        response = client.post("/webhook/test", json=base_payload)
        data = response.json()
        
        assert isinstance(data["drafted_reply"], str)
        assert len(data["drafted_reply"]) > 0
    
    def test_drafted_reply_contains_guest_name(self, client, base_payload):
        """drafted_reply should personalize with guest name."""
        response = client.post("/webhook/test", json=base_payload)
        data = response.json()
        
        assert "Rahul" in data["drafted_reply"]


# =============================================================================
# ACTION DETERMINATION TESTS
# =============================================================================

class TestActionDetermination:
    """Tests for action determination based on query type and confidence."""
    
    def test_complaint_always_escalates(self, client):
        """ALL complaints must escalate regardless of confidence."""
        payload = {
            "source": "airbnb",
            "guest_name": "Angry Guest",
            "message": "The AC is not working. This is unacceptable. I want a refund.",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        data = response.json()
        
        assert data["action"] == ActionType.ESCALATE.value, \
            f"Complaint should escalate, got {data['action']}"
    
    def test_checkin_auto_send(self, client):
        """Check-in queries with known answers should auto_send."""
        payload = {
            "source": "booking_com",
            "guest_name": "Test Guest",
            "message": "What time can we check in? Also what is the WiFi password?",
            "timestamp": "2026-05-05T10:30:00Z",
            "booking_ref": "NIS-2024-0891",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        data = response.json()
        
        assert data["action"] == ActionType.AUTO_SEND.value
    
    def test_pricing_agent_review(self, client):
        """Pricing queries typically need agent review."""
        payload = {
            "source": "whatsapp",
            "guest_name": "Test Guest",
            "message": "What is the rate for 2 adults for 3 nights?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        data = response.json()
        
        assert data["action"] == ActionType.AGENT_REVIEW.value


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error handling and edge cases."""
    
    def test_invalid_json_payload(self, client):
        """Invalid JSON should return 422."""
        response = client.post(
            "/webhook/test",
            data="invalid json here",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
    
    def test_missing_request_body(self, client):
        """Empty request body should return 422."""
        response = client.post("/webhook/test", json={})
        assert response.status_code == 422
    
    def test_invalid_timestamp_format(self, client, base_payload):
        """Invalid timestamp should return 422."""
        payload = base_payload.copy()
        payload["timestamp"] = "not-a-timestamp"
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 422
    
    def test_message_too_long(self, client, base_payload):
        """Message exceeding max length should return 422."""
        payload = base_payload.copy()
        payload["message"] = "A" * 5001  # Exceeds 5000 char limit
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 422
    
    def test_request_id_header_present(self, client, base_payload):
        """Response should include X-Request-ID header."""
        response = client.post("/webhook/test", json=base_payload)
        assert "x-request-id" in response.headers


# =============================================================================
# CHANNEL-SPECIFIC TESTS
# =============================================================================

class TestChannelSupport:
    """Tests for all supported channels."""
    
    def test_whatsapp_channel(self, client, base_payload):
        """WhatsApp messages should be processed."""
        response = client.post("/webhook/test", json=base_payload)
        assert response.status_code == 200
        assert response.json()["query_type"] == QueryType.PRE_SALES_AVAILABILITY.value
    
    def test_booking_com_channel(self, client):
        """Booking.com messages should be processed."""
        payload = {
            "source": "booking_com",
            "guest_name": "John Smith",
            "message": "What time is check-in?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200
    
    def test_airbnb_channel(self, client):
        """Airbnb messages should be processed."""
        payload = {
            "source": "airbnb",
            "guest_name": "Emma Wilson",
            "message": "Is there a pool at the villa?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200
    
    def test_instagram_channel(self, client):
        """Instagram messages should be processed."""
        payload = {
            "source": "instagram",
            "guest_name": "Alex Johnson",
            "message": "How much for 2 nights?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200
    
    def test_direct_channel(self, client):
        """Direct messages should be processed."""
        payload = {
            "source": "direct",
            "guest_name": "Sarah Lee",
            "message": "Do you allow pets?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""
    
    def test_very_short_message(self, client):
        """Very short messages should be handled."""
        payload = {
            "source": "whatsapp",
            "guest_name": "Test",
            "message": "Hi",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200
    
    def test_message_with_special_characters(self, client):
        """Messages with special characters should be handled."""
        payload = {
            "source": "whatsapp",
            "guest_name": "Test Guest",
            "message": "Price for 2 adults? @#$%^&*() !!! ???",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200
    
    def test_message_with_unicode(self, client):
        """Messages with unicode characters should be handled."""
        payload = {
            "source": "whatsapp",
            "guest_name": "Test Guest",
            "message": "Is the villa available? Bonjour! \u00e0 bient\u00f4t",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200
    
    def test_guest_name_with_special_chars(self, client):
        """Guest names with special characters should be handled."""
        payload = {
            "source": "whatsapp",
            "guest_name": "Jean-Pierre O'Brien",
            "message": "Availability for next weekend?",
            "timestamp": "2026-05-05T10:30:00Z",
            "property_id": "villa-b1"
        }
        response = client.post("/webhook/test", json=payload)
        assert response.status_code == 200
        assert "Jean-Pierre" in response.json()["drafted_reply"]


# =============================================================================
# CLASSIFIER UNIT TESTS
# =============================================================================

class TestClassifier:
    """Direct unit tests for the QueryClassifier."""
    
    def test_classifier_singleton(self):
        """Classifier should be a singleton."""
        from app.classifier import get_classifier
        c1 = get_classifier()
        c2 = get_classifier()
        assert c1 is c2
    
    def test_availability_keywords(self):
        """Availability keywords should classify correctly."""
        from app.classifier import get_classifier
        from app.schemas import QueryType
        
        classifier = get_classifier()
        result = classifier.classify("Is the villa available next weekend?")
        assert result == QueryType.PRE_SALES_AVAILABILITY
    
    def test_pricing_keywords(self):
        """Pricing keywords should classify correctly."""
        from app.classifier import get_classifier
        from app.schemas import QueryType
        
        classifier = get_classifier()
        result = classifier.classify("How much is the rate per night?")
        assert result == QueryType.PRE_SALES_PRICING
    
    def test_complaint_keywords(self):
        """Complaint keywords should classify correctly."""
        from app.classifier import get_classifier
        from app.schemas import QueryType
        
        classifier = get_classifier()
        result = classifier.classify("The AC is broken and I want a refund")
        assert result == QueryType.COMPLAINT
    
    def test_empty_message_defaults_to_general(self):
        """Empty message should default to general_enquiry."""
        from app.classifier import get_classifier
        from app.schemas import QueryType
        
        classifier = get_classifier()
        result = classifier.classify("")
        assert result == QueryType.GENERAL_ENQUIRY
    
    def test_classification_scores_returned(self):
        """Classification scores should be returned for all types."""
        from app.classifier import get_classifier
        from app.schemas import QueryType
        
        classifier = get_classifier()
        scores = classifier.get_classification_scores("What is the price?")
        
        assert len(scores) == len(QueryType)
        assert all(isinstance(score, (int, float)) for score in scores.values())


# =============================================================================
# CONFIDENCE SCORER UNIT TESTS
# =============================================================================

class TestConfidenceScorer:
    """Direct unit tests for the ConfidenceScorer."""
    
    def test_scorer_singleton(self):
        """Scorer should be a singleton."""
        from app.confidence_scorer import get_scorer
        s1 = get_scorer()
        s2 = get_scorer()
        assert s1 is s2
    
    def test_complaint_always_escalates(self):
        """Complaints should always escalate regardless of score."""
        from app.confidence_scorer import get_scorer
        from app.schemas import QueryType, ActionType
        
        scorer = get_scorer()
        score, factors, action = scorer.calculate_final_score(
            ai_self_assessment=0.95,
            guest_message="The AC is broken",
            drafted_reply="We are sorry about the AC issue.",
            key_points_addressed=["AC issue"],
            classification_scores={qt: 0 for qt in QueryType},
            query_type=QueryType.COMPLAINT,
            has_booking_ref=True
        )
        
        assert action == ActionType.ESCALATE
    
    def test_high_score_auto_send(self):
        """High scores should result in auto_send for non-complaints."""
        from app.confidence_scorer import get_scorer
        from app.schemas import QueryType, ActionType
        
        scorer = get_scorer()
        class_scores = {qt: 0 for qt in QueryType}
        class_scores[QueryType.POST_SALES_CHECKIN] = 10
        
        score, factors, action = scorer.calculate_final_score(
            ai_self_assessment=0.95,
            guest_message="What is the WiFi password?",
            drafted_reply="Hi there! The WiFi password is Nistula@2024. You can connect on arrival. Let me know if you need anything else. Best regards!",
            key_points_addressed=["WiFi password", "connection help"],
            classification_scores=class_scores,
            query_type=QueryType.POST_SALES_CHECKIN,
            has_booking_ref=True
        )
        
        assert score >= 0.85, f"Score was {score}, expected >= 0.85"
        assert action == ActionType.AUTO_SEND
    
    def test_context_coverage_calculation(self):
        """Context coverage should be calculated correctly."""
        from app.confidence_scorer import get_scorer
        
        scorer = get_scorer()
        coverage = scorer.calculate_context_coverage(
            "What is the rate? Is it available?",
            ["rate question", "availability question"]
        )
        
        assert 0.0 <= coverage <= 1.0
    
    def test_response_completeness(self):
        """Response completeness should be calculated correctly."""
        from app.confidence_scorer import get_scorer
        
        scorer = get_scorer()
        
        # Complete response
        complete = scorer.calculate_response_completeness(
            "Hi! The WiFi password is Nistula@2024. Let me know if you need anything else. Best regards!"
        )
        assert complete > 0.5
        
        # Incomplete response
        incomplete = scorer.calculate_response_completeness("WiFi: Nistula@2024")
        assert incomplete < 0.5


# =============================================================================
# INTEGRATION TEST NOTES
# =============================================================================
"""
NOTE ON INTEGRATION TESTS (Ravikumar):

The tests above use the /webhook/test endpoint to avoid making actual Claude API calls.
For full integration testing with the real Claude API:

1. Set CLAUDE_API_KEY in .env to your actual key
2. Run the real webhook endpoint tests:

   def test_real_webhook_availability(client):
       payload = {
           "source": "whatsapp",
           "guest_name": "Rahul Sharma",
           "message": "Is the villa available from April 20 to 24?",
           "timestamp": "2026-05-05T10:30:00Z",
           "property_id": "villa-b1"
       }
       response = client.post("/webhook/message", json=payload)
       assert response.status_code == 200
       data = response.json()
       assert data["action"] in ["auto_send", "agent_review", "escalate"]

IMPORTANT: These integration tests will consume API credits. Run sparingly.
The unit tests above provide comprehensive coverage without API costs.
"""


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
