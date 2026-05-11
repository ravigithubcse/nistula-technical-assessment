"""
Confidence Scoring Module
Author: Ravikumar

Calculates a confidence score (0.0 to 1.0) for each AI-generated reply.
The score determines the action: auto_send, agent_review, or escalate.

Confidence Scoring Logic (Explained in Detail):
================================================

The confidence score is a weighted composite of multiple factors:

1. AI_SELF_ASSESSMENT (40% weight):
   - Claude's own confidence rating about the accuracy of its response
   - Based on how well the prompt context matches the query
   - Range: 0.0 to 1.0

2. CONTEXT_COVERAGE (30% weight):
   - Measures how much of the guest's message was addressed
   - Calculated as: (points_addressed / total_points_in_query)
   - Ensures no guest questions are accidentally ignored

3. QUERY_TYPE_CONFIDENCE (20% weight):
   - How confident we are in the query classification
   - Based on the margin between top-scoring and second-scoring category
   - Higher margin = more confident classification

4. RESPONSE_COMPLETENESS (10% weight):
   - Checks if the response contains all required elements
   - Greeting, relevant info, next steps, friendly closing
   - Penalizes overly short or vague responses

Final Action Determination:
- score >= 0.85: auto_send    - High confidence, safe to automate
- 0.60 <= score < 0.85: agent_review - Needs human eyes before sending
- score < 0.60: escalate      - Low confidence or complaint, human takeover

Special Rules:
- ALL complaints automatically escalate (guest satisfaction priority)
- Messages with booking_ref get +0.05 boost (known guest context)
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.schemas import ActionType, QueryType


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# Weight distribution for confidence factors
# Design Decision (Ravikumar): Weights sum to 1.0 for predictable scoring
WEIGHT_AI_SELF = 0.40
WEIGHT_CONTEXT = 0.30
WEIGHT_QUERY_TYPE = 0.20
WEIGHT_COMPLETENESS = 0.10

# Action thresholds
# Design Decision (Ravikumar): These are configurable for business tuning
THRESHOLD_AUTO_SEND = 0.85
THRESHOLD_AGENT_REVIEW = 0.60

# Boost for known guests (have booking reference)
KNOWN_GUEST_BOOST = 0.05

# Minimum and maximum possible scores
MIN_SCORE = 0.0
MAX_SCORE = 1.0


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ConfidenceFactors:
    """
    Individual factors that contribute to the final confidence score.
    
    Design Decision (Ravikumar):
    - Breaking down into factors provides transparency and debuggability
    - Each factor can be logged and analyzed separately
    - Easy to adjust weights or add new factors over time
    """
    ai_self_assessment: float = 0.0       # Claude's own confidence (0-1)
    context_coverage: float = 0.0          # How well guest query was addressed (0-1)
    query_type_confidence: float = 0.0     # Confidence in query classification (0-1)
    response_completeness: float = 0.0     # Does response have all parts? (0-1)
    known_guest_boost: float = 0.0         # Bonus for returning guests (0-0.05)
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary for logging and serialization."""
        return {
            "ai_self_assessment": round(self.ai_self_assessment, 4),
            "context_coverage": round(self.context_coverage, 4),
            "query_type_confidence": round(self.query_type_confidence, 4),
            "response_completeness": round(self.response_completeness, 4),
            "known_guest_boost": round(self.known_guest_boost, 4),
        }


# =============================================================================
# CONFIDENCE SCORER CLASS
# =============================================================================

class ConfidenceScorer:
    """
    Calculates confidence scores for AI-generated replies.
    
    Design Decision (Ravikumar):
    - Multi-factor scoring provides more reliable results than single-metric
    - Each factor addresses a different dimension of "confidence"
    - Composite approach reduces false positives in auto_send
    - Transparent scoring helps with debugging and continuous improvement
    """
    
    def __init__(self):
        """Initialize the confidence scorer with default weights."""
        self.weights = {
            "ai_self": WEIGHT_AI_SELF,
            "context": WEIGHT_CONTEXT,
            "query_type": WEIGHT_QUERY_TYPE,
            "completeness": WEIGHT_COMPLETENESS,
        }
    
    def calculate_context_coverage(
        self,
        guest_message: str,
        key_points_addressed: List[str]
    ) -> float:
        """
        Calculate how much of the guest's message was addressed.
        
        Algorithm:
        1. Extract potential questions/requests from guest message
        2. Count how many were addressed in the response
        3. Return coverage ratio (addressed / total)
        
        Args:
            guest_message: Original message from guest
            key_points_addressed: Points the AI claims to have addressed
            
        Returns:
            float: Coverage score between 0.0 and 1.0
        """
        # Extract sentences that look like questions
        question_indicators = [
            r'\?',  # Contains question mark
            r'\b(what|how|when|where|why|is|are|can|could|would|will|do|does)\b',  # Question words
            r'\b(available|rate|price|cost|check|wifi|password|refund|compensat)\b',  # Query keywords
        ]
        
        # Count potential questions in guest message
        potential_questions = 0
        sentences = re.split(r'[.!?]+', guest_message.lower())
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            for pattern in question_indicators:
                if re.search(pattern, sentence, re.IGNORECASE):
                    potential_questions += 1
                    break
        
        # If no clear questions found, assume at least 1 implicit query
        potential_questions = max(potential_questions, 1)
        
        # Points addressed by AI
        points_addressed = max(len(key_points_addressed), 0)
        
        # Coverage ratio (capped at 1.0)
        coverage = min(points_addressed / potential_questions, 1.0)
        
        return coverage
    
    def calculate_query_type_confidence(
        self,
        classification_scores: Dict[QueryType, int]
    ) -> float:
        """
        Calculate confidence in the query classification.
        
        Algorithm:
        - Based on the margin between top and second-highest scores
        - Larger margin = more confident classification
        - If scores are close, classification is ambiguous
        
        Args:
            classification_scores: Raw scores from the classifier
            
        Returns:
            float: Query type confidence between 0.0 and 1.0
        """
        if not classification_scores:
            return 0.0
        
        sorted_scores = sorted(classification_scores.values(), reverse=True)
        
        if len(sorted_scores) == 0:
            return 0.0
        
        top_score = sorted_scores[0]
        
        if len(sorted_scores) == 1:
            # Only one category scored - moderate confidence
            return 0.7 if top_score > 0 else 0.0
        
        second_score = sorted_scores[1]
        
        if top_score == 0:
            return 0.0  # No category matched at all
        
        # Calculate margin ratio
        # Higher margin = more confident
        total = top_score + second_score
        if total == 0:
            return 0.0
        
        margin = (top_score - second_score) / total
        
        # Scale to 0-1 range (margin is naturally 0-1)
        # Apply scaling: even 50% margin gives decent confidence
        confidence = min(margin * 2, 1.0)
        
        return max(confidence, 0.1)  # Minimum 0.1 if there was any match
    
    def calculate_response_completeness(self, drafted_reply: str) -> float:
        """
        Check if the response has all essential parts.
        
        Checks for:
        1. Greeting (personalized)
        2. Relevant answer content
        3. Next steps or call-to-action
        4. Friendly closing
        
        Args:
            drafted_reply: The AI-generated response
            
        Returns:
            float: Completeness score between 0.0 and 1.0
        """
        if not drafted_reply or len(drafted_reply) < 20:
            return 0.1  # Too short to be complete
        
        reply_lower = drafted_reply.lower()
        score = 0.0
        
        # Check for greeting (0.25)
        greeting_patterns = [
            r'\b(hi|hello|hey|dear|greetings)\b',
            r'^(hi|hello|hey)',
        ]
        for pattern in greeting_patterns:
            if re.search(pattern, reply_lower):
                score += 0.25
                break
        
        # Check for substantive content (0.25)
        # Response should have multiple sentences
        sentences = [s.strip() for s in re.split(r'[.!?]+', drafted_reply) if s.strip()]
        if len(sentences) >= 2:
            score += 0.25
        
        # Check for next steps or actionable info (0.25)
        action_patterns = [
            r'\b(let me know|feel free|reach out|contact|call|reply)\b',
            r'\b(book|confirm|reserve|check)\b',
            r'\b(here is|here are|you can|we can)\b',
        ]
        for pattern in action_patterns:
            if re.search(pattern, reply_lower):
                score += 0.25
                break
        
        # Check for friendly closing (0.25)
        closing_patterns = [
            r'\b(best|regards|cheers|thank|thanks|looking forward|have a great|enjoy)\b',
        ]
        # Check in last 100 chars for closing
        ending = reply_lower[-100:]
        for pattern in closing_patterns:
            if re.search(pattern, ending):
                score += 0.25
                break
        
        return score
    
    def calculate_final_score(
        self,
        ai_self_assessment: float,
        guest_message: str,
        drafted_reply: str,
        key_points_addressed: List[str],
        classification_scores: Dict[QueryType, int],
        query_type: QueryType,
        has_booking_ref: bool = False
    ) -> tuple[float, ConfidenceFactors, ActionType]:
        """
        Calculate the final confidence score and determine action.
        
        This is the main entry point for scoring a response.
        
        Args:
            ai_self_assessment: Claude's self-rated confidence (0-1)
            guest_message: Original guest message
            drafted_reply: AI-generated response
            key_points_addressed: Points addressed in the response
            classification_scores: Raw classifier scores
            query_type: Classified query type
            has_booking_ref: Whether guest has a booking reference
            
        Returns:
            Tuple of (final_score, factors, action)
        """
        factors = ConfidenceFactors()
        
        # Factor 1: AI self-assessment (40%)
        factors.ai_self_assessment = max(0.0, min(1.0, ai_self_assessment))
        
        # Factor 2: Context coverage (30%)
        factors.context_coverage = self.calculate_context_coverage(
            guest_message, key_points_addressed
        )
        
        # Factor 3: Query type confidence (20%)
        factors.query_type_confidence = self.calculate_query_type_confidence(
            classification_scores
        )
        
        # Factor 4: Response completeness (10%)
        factors.response_completeness = self.calculate_response_completeness(
            drafted_reply
        )
        
        # Known guest boost
        if has_booking_ref:
            factors.known_guest_boost = KNOWN_GUEST_BOOST
        
        # Calculate weighted composite score
        final_score = (
            factors.ai_self_assessment * self.weights["ai_self"] +
            factors.context_coverage * self.weights["context"] +
            factors.query_type_confidence * self.weights["query_type"] +
            factors.response_completeness * self.weights["completeness"] +
            factors.known_guest_boost
        )
        
        # Clamp to valid range
        final_score = max(MIN_SCORE, min(MAX_SCORE, final_score))
        
        # Determine action based on score and query type
        action = self._determine_action(final_score, query_type)
        
        return round(final_score, 4), factors, action
    
    def _determine_action(self, score: float, query_type: QueryType) -> ActionType:
        """
        Determine the action based on confidence score and query type.
        
        Business Rules (Ravikumar):
        - ALL complaints escalate (guest satisfaction is priority)
        - Score >= 0.85: Auto-send (high confidence)
        - Score 0.60-0.85: Agent review (medium confidence, human check)
        - Score < 0.60: Escalate (low confidence, needs human)
        
        Args:
            score: Final confidence score
            query_type: Classified query type
            
        Returns:
            ActionType: The determined action
        """
        # Special rule: All complaints escalate immediately
        if query_type == QueryType.COMPLAINT:
            return ActionType.ESCALATE
        
        # Standard scoring logic
        if score >= THRESHOLD_AUTO_SEND:
            return ActionType.AUTO_SEND
        elif score >= THRESHOLD_AGENT_REVIEW:
            return ActionType.AGENT_REVIEW
        else:
            return ActionType.ESCALATE


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_scorer: ConfidenceScorer | None = None


def get_scorer() -> ConfidenceScorer:
    """Get or create the singleton ConfidenceScorer instance."""
    global _scorer
    if _scorer is None:
        _scorer = ConfidenceScorer()
    return _scorer
