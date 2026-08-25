"""Scoring engine wrapper — three-tier fraud decision bands.

Wraps the existing check_transaction handler with:
- Three-tier bands: APPROVE (0-29), REVIEW (30-59), REJECT (>=60)
- Silent failure detection (fast zero-score → REVIEW)
- Token expiry / AWS error handling (→ REVIEW, never false APPROVE)
- Circuit breaker after consecutive failures
"""

import logging
import os
import sys
import time
from typing import Dict

from botocore.exceptions import ClientError

# Ensure project root is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lambdas.fraud_check.handler import check_transaction, RULE_WEIGHTS
from streamlit_app.config.settings import BAND_APPROVE_MAX, BAND_REVIEW_MAX

logger = logging.getLogger(__name__)

# Circuit breaker state
_consecutive_failures: int = 0
_CIRCUIT_BREAKER_THRESHOLD: int = 3
_FAST_RESPONSE_MS: float = 100.0  # If score=0 AND faster than this, likely a failure


def _classify_band(risk_score: int) -> str:
    """Classify a numeric risk score into a three-tier decision band.

    Args:
        risk_score: Integer score from 0-130 (sum of rule weights).

    Returns:
        One of 'APPROVE', 'REVIEW', or 'REJECT'.
    """
    if risk_score <= BAND_APPROVE_MAX:
        return "APPROVE"
    elif risk_score <= BAND_REVIEW_MAX:
        return "REVIEW"
    else:
        return "REJECT"


def _is_silent_failure(result: Dict, elapsed_ms: float) -> bool:
    """Detect silent handler failures.

    The existing check_transaction returns score=0 when Neptune queries fail
    (execute_query returns [] on error). This looks like a clean genuine
    customer but is actually a service error.

    Detection: score=0 AND zero rules triggered is suspicious. In the POC
    graph, even genuine accounts trigger at least one rule (shared_device).
    A truly clean result with zero rules almost always means all queries
    failed silently (e.g., auth failure, Neptune down).
    """
    return (
        result.get("risk_score", 0) == 0
        and result.get("rule_count", 0) == 0
    )


def score_transaction(
    account_id: str,
    merchant_id: str,
    amount: float,
    transaction_id: str = "",
) -> Dict:
    """Score a transaction through Tier 1 rules with three-tier band classification.

    This wraps check_transaction() and adds:
    - Three-tier decision: APPROVE / REVIEW / REJECT
    - Silent failure detection
    - AWS error handling (safe default = REVIEW)
    - Circuit breaker

    Args:
        account_id: Account identifier (e.g., 'A0006').
        merchant_id: Merchant identifier (e.g., 'M0015').
        amount: Transaction amount in dollars.
        transaction_id: Optional transaction identifier.

    Returns:
        Dict with keys: transaction_id, account_id, merchant_id, amount,
        risk_score, decision (three-tier), rules_triggered, latency_ms,
        warnings (list of any issues detected).
    """
    global _consecutive_failures
    warnings = []

    # Circuit breaker: if too many consecutive failures, skip Neptune
    if _consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
        logger.warning("Circuit breaker OPEN — returning REVIEW without Neptune call")
        _consecutive_failures += 1  # Keep counting
        return {
            "transaction_id": transaction_id,
            "account_id": account_id,
            "merchant_id": merchant_id,
            "amount": amount,
            "risk_score": 35,  # Mid-REVIEW band
            "decision": "REVIEW",
            "rules_triggered": [],
            "rule_count": 0,
            "latency_ms": 0.0,
            "warnings": ["Circuit breaker open — Neptune may be unreachable. "
                         "Score defaulted to REVIEW."],
            "tier": 1,
        }

    # Call the existing handler
    start_ms = time.time() * 1000
    try:
        result = check_transaction(account_id, merchant_id, amount, transaction_id)
        elapsed_ms = (time.time() * 1000) - start_ms

        # Silent failure detection
        if _is_silent_failure(result, elapsed_ms):
            logger.warning(
                "Silent failure detected: score=0 in %.0fms for %s",
                elapsed_ms, account_id,
            )
            warnings.append(
                f"Score zero with fast response ({elapsed_ms:.0f}ms) — "
                "possible service error. Defaulting to REVIEW."
            )
            _consecutive_failures += 1
            result["risk_score"] = 35
            result["decision"] = "REVIEW"
        else:
            # Successful call — reset circuit breaker
            _consecutive_failures = 0

    except ClientError as e:
        elapsed_ms = (time.time() * 1000) - start_ms
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.error("AWS error during scoring: %s — %s", error_code, e)
        _consecutive_failures += 1

        if "ExpiredToken" in error_code or "Credentials" in error_code:
            warning_msg = "AWS session expired — please re-authenticate"
        else:
            warning_msg = f"AWS error ({error_code}) — defaulting to REVIEW"

        warnings.append(warning_msg)
        return {
            "transaction_id": transaction_id,
            "account_id": account_id,
            "merchant_id": merchant_id,
            "amount": amount,
            "risk_score": 35,
            "decision": "REVIEW",
            "rules_triggered": [],
            "rule_count": 0,
            "latency_ms": round(elapsed_ms, 1),
            "warnings": warnings,
            "tier": 1,
        }

    except Exception as e:
        elapsed_ms = (time.time() * 1000) - start_ms
        logger.error("Unexpected error during scoring: %s", e)
        _consecutive_failures += 1
        warnings.append(f"Unexpected error — defaulting to REVIEW: {e}")
        return {
            "transaction_id": transaction_id,
            "account_id": account_id,
            "merchant_id": merchant_id,
            "amount": amount,
            "risk_score": 35,
            "decision": "REVIEW",
            "rules_triggered": [],
            "rule_count": 0,
            "latency_ms": round(elapsed_ms, 1),
            "warnings": warnings,
            "tier": 1,
        }

    # Apply three-tier classification
    score = result.get("risk_score", 0)
    decision = _classify_band(score)

    # Override the handler's binary APPROVE/FLAG with our three-tier band
    result["decision"] = decision
    result["warnings"] = warnings
    result["tier"] = 1

    return result


def reset_circuit_breaker() -> None:
    """Manually reset the circuit breaker (e.g., after reconnecting)."""
    global _consecutive_failures
    _consecutive_failures = 0
    logger.info("Circuit breaker reset")
