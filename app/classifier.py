"""
Query Classification Module
Author: Ravikumar

Classifies guest messages into predefined query types using keyword analysis
and pattern matching. This is a lightweight classifier that runs before
sending to Claude AI, ensuring the AI prompt is contextualized correctly.
"""

import re
from typing import Dict, List, Tuple

from app.schemas import QueryType


# =============================================================================
# CLASSIFICATION KEYWORDS AND PATTERNS
# =============================================================================

# Keyword mapping for each query type
# Design Decision (Ravikumar):
# - Using weighted keywords for classification accuracy
# - Higher weight = stronger indicator of that query type
# - Compound queries (e.g., "availability + pricing") are handled by scoring

CLASSIFICATION_KEYWORDS: Dict[QueryType, List[Tuple[str, int]]] = {
    QueryType.PRE_SALES_AVAILABILITY: [
        # Keywords with their weights (higher = more specific to this category)
        ("available", 3), ("availability", 3), ("free", 2), ("booked", 2),
        ("vacant", 3), ("open", 1), ("dates", 2), ("check in", 2),
        ("check-in", 2), ("stay", 1), ("from", 1), ("to", 1),
        ("april", 1), ("may", 1), ("june", 1), ("july", 1),
        ("august", 1), ("september", 1), ("october", 1),
        ("november", 1), ("december", 1), ("january", 1),
        ("february", 1), ("march", 1), ("nights", 2), ("weekend", 1),
        ("week", 1), ("any dates", 3), ("open dates", 3),
    ],
    QueryType.PRE_SALES_PRICING: [
        ("rate", 3), ("price", 3), ("cost", 3), ("pricing", 3),
        ("how much", 3), ("charges", 2), ("fee", 2), ("fees", 2),
        ("payment", 2), ("pay", 2), ("expensive", 1), ("cheap", 1),
        ("discount", 2), ("offer", 2), ("deal", 1), ("package", 2),
        ("per night", 3), ("total cost", 3), ("how much is", 3),
        ("what is the rate", 3), ("what is the price", 3),
        ("budget", 1), ("affordable", 1),
    ],
    QueryType.POST_SALES_CHECKIN: [
        ("check in", 2), ("check-in", 2), ("check out", 2), ("check-out", 2),
        ("wifi", 3), ("password", 2), ("key", 2), ("directions", 2),
        ("address", 2), ("location", 1), ("parking", 2), ("arrival", 2),
        ("arriving", 2), ("reach", 1), ("entry", 2), ("door", 1),
        ("lock", 1), ("access", 2), ("wifi password", 3), ("internet", 2),
        ("checkin time", 3), ("checkout time", 3), ("what time", 1),
        ("how do i", 1), ("where is", 1),
    ],
    QueryType.SPECIAL_REQUEST: [
        ("early check", 3), ("late check", 3), ("airport", 3),
        ("transfer", 2), ("pickup", 2), ("drop", 1), ("cab", 2),
        ("taxi", 2), ("birthday", 2), ("anniversary", 2),
        ("celebration", 2), ("cake", 1), ("decoration", 2),
        ("extra bed", 2), ("cot", 1), ("crib", 1), ("baby", 1),
        ("pet", 2), ("dog", 1), ("cat", 1), ("wheelchair", 2),
        ("accessible", 2), ("special", 1), ("request", 1),
        ("can you arrange", 2), ("arrange for", 2), ("help with", 1),
        ("breakfast", 1), ("lunch", 1), ("dinner", 1), ("chef", 2),
        ("cooking", 1),
    ],
    QueryType.COMPLAINT: [
        ("not working", 3), ("broken", 3), ("problem", 2), ("issue", 2),
        ("complaint", 3), ("unhappy", 3), ("disappointed", 3),
        ("terrible", 3), ("worst", 3), ("bad", 2), ("poor", 2),
        ("horrible", 3), ("awful", 3), ("unacceptable", 3),
        ("refund", 3), ("money back", 3), ("compensate", 2),
        ("compensation", 2), ("not clean", 3), ("dirty", 3),
        ("no hot water", 3), ("ac not", 3), ("noise", 2),
        ("bug", 2), ("insect", 2), ("cockroach", 3),
        ("not working", 3), ("angry", 2), ("frustrated", 2),
        ("ridiculous", 2), ("unprofessional", 2),
    ],
    QueryType.GENERAL_ENQUIRY: [
        ("pet", 2), ("dog", 1), ("cat", 1), ("animal", 1),
        ("pool", 2), ("swimming", 1), ("gym", 1), ("restaurant", 1),
        ("food", 1), ("nearby", 1), ("attractions", 1),
        ("beach", 1), ("market", 1), ("shop", 1), ("store", 1),
        ("hospital", 1), ("pharmacy", 1), ("medical", 1),
        ("allowed", 3), ("permitted", 2), ("rules", 1),
        ("policy", 1), ("smoking", 2), ("alcohol", 1),
        ("children", 1), ("kids", 1), ("family", 1),
        ("party", 2), ("event", 1), ("gathering", 1),
        ("bathroom", 1), ("toilet", 1), ("kitchen", 1),
        ("amenities", 2), ("facilities", 2), ("services", 1),
        ("allow pets", 4), ("allow dogs", 4), ("pet friendly", 4),
        ("pet policy", 4), ("parking", 3), ("car park", 3),
    ],
}


# =============================================================================
# CLASSIFIER CLASS
# =============================================================================

class QueryClassifier:
    """
    Lightweight keyword-based query classifier.
    
    Design Decision (Ravikumar):
    - Using keyword scoring instead of ML model for speed and simplicity
    - Weights ensure specific terms have higher classification impact
    - Handles multi-intent messages by selecting highest-scoring category
    - Falls back to general_enquiry when no clear category is detected
    
    Future Enhancement:
    - Could be replaced with fine-tuned BERT model for higher accuracy
    - Could use Claude itself for classification via separate API call
    """
    
    def __init__(self):
        """Initialize classifier with compiled keyword patterns for performance."""
        self._compiled_patterns: Dict[QueryType, List[Tuple[re.Pattern, int]]] = {}
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """
        Pre-compile regex patterns for all keywords.
        
        Performance Optimization (Ravikumar):
        - Compiling patterns once at initialization avoids recompilation per request
        - Using word boundary regex for accurate matching (avoids partial matches)
        - Case-insensitive matching for robustness
        """
        for query_type, keywords in CLASSIFICATION_KEYWORDS.items():
            compiled = []
            for keyword, weight in keywords:
                # Use word boundaries for multi-word patterns, simple contains for short words
                if len(keyword) > 3 and " " in keyword:
                    pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
                else:
                    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                compiled.append((pattern, weight))
            self._compiled_patterns[query_type] = compiled
    
    def classify(self, message_text: str) -> QueryType:
        """
        Classify a message into a query type.
        
        Algorithm (Ravikumar):
        1. Score the message against each query type's keywords
        2. Keyword matches are weighted by their importance
        3. The query type with the highest total score wins
        4. If no keywords match, default to general_enquiry
        
        Args:
            message_text: The raw message text from the guest
            
        Returns:
            QueryType: The classified query category
        """
        if not message_text or not message_text.strip():
            # Empty messages default to general enquiry
            return QueryType.GENERAL_ENQUIRY
        
        scores: Dict[QueryType, int] = {qt: 0 for qt in QueryType}
        
        # Score each query type
        for query_type, patterns in self._compiled_patterns.items():
            for pattern, weight in patterns:
                matches = len(pattern.findall(message_text))
                if matches > 0:
                    scores[query_type] += matches * weight
        
        # Find the query type with highest score
        max_score = max(scores.values())
        
        if max_score == 0:
            # No keywords matched - this is a general enquiry
            return QueryType.GENERAL_ENQUIRY
        
        # Get all query types with the max score (handle ties)
        best_matches = [qt for qt, score in scores.items() if score == max_score]
        
        # If there's a tie, prefer specific categories over general_enquiry
        if len(best_matches) > 1 and QueryType.GENERAL_ENQUIRY in best_matches:
            best_matches.remove(QueryType.GENERAL_ENQUIRY)
        
        # Return the first best match (deterministic since dict order is preserved)
        return best_matches[0]
    
    def get_classification_scores(self, message_text: str) -> Dict[QueryType, int]:
        """
        Get raw scores for all query types (useful for debugging and analytics).
        
        Args:
            message_text: The raw message text from the guest
            
        Returns:
            Dict mapping QueryType to its score
        """
        scores: Dict[QueryType, int] = {qt: 0 for qt in QueryType}
        
        for query_type, patterns in self._compiled_patterns.items():
            for pattern, weight in patterns:
                matches = len(pattern.findall(message_text))
                if matches > 0:
                    scores[query_type] += matches * weight
        
        return scores


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

# Singleton instance for application-wide use
# Design Decision (Ravikumar):
# - Single shared instance avoids recreating the classifier per request
# - Thread-safe since patterns are read-only after initialization
_classifier: QueryClassifier | None = None


def get_classifier() -> QueryClassifier:
    """Get or create the singleton QueryClassifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = QueryClassifier()
    return _classifier
