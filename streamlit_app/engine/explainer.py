"""Explainer engine wrapper — Tier 2 LLM-based explanation with fallback.

Wraps the existing gather_evidence and generate_explanation handlers with:
- Configurable timeout
- Bedrock unavailability fallback (template-based explanation)
- Never crashes the app — always returns something useful
"""

import logging
import os
import sys
import time
from typing import Dict, Optional

from botocore.exceptions import ClientError

# Ensure project root is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lambdas.explain.handler import (
    gather_evidence,
    generate_explanation,
    _template_explanation,
)
from streamlit_app.config.settings import TIER2_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


def get_evidence(entity_id: str, max_hops: int = 3) -> Dict:
    """Gather graph evidence for an entity, with error handling.

    Args:
        entity_id: Account or entity identifier (e.g., 'A0009').
        max_hops: Maximum graph traversal depth.

    Returns:
        Evidence dict with findings, or a minimal error evidence dict.
    """
    try:
        evidence = gather_evidence(entity_id, max_hops)
        return evidence
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.error("Evidence gathering failed: %s", e)
        return {
            "entity_id": entity_id,
            "findings": [],
            "error": f"Evidence unavailable ({error_code})",
        }
    except Exception as e:
        logger.error("Unexpected error gathering evidence: %s", e)
        return {
            "entity_id": entity_id,
            "findings": [],
            "error": f"Evidence unavailable: {e}",
        }


def get_explanation(evidence: Dict) -> Dict:
    """Generate a natural language explanation from evidence.

    Tries Bedrock LLM first, falls back to template if unavailable.
    Never raises — always returns a usable result.

    Args:
        evidence: Evidence dict from get_evidence().

    Returns:
        Dict with 'explanation' (str), 'source' ('llm' or 'template'),
        'latency_s' (float), and optional 'warning' (str).
    """
    start = time.time()
    warning = None

    # If evidence gathering itself failed, use template directly
    if evidence.get("error"):
        explanation = _template_explanation(evidence)
        return {
            "explanation": explanation,
            "source": "template",
            "latency_s": round(time.time() - start, 2),
            "warning": f"Using template — {evidence['error']}",
        }

    try:
        explanation = generate_explanation(evidence)
        elapsed = time.time() - start

        if elapsed > TIER2_TIMEOUT_SECONDS:
            warning = f"Explanation took {elapsed:.1f}s (threshold: {TIER2_TIMEOUT_SECONDS}s)"

        return {
            "explanation": explanation,
            "source": "llm",
            "latency_s": round(elapsed, 2),
            "warning": warning,
        }

    except ClientError as e:
        elapsed = time.time() - start
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.warning("Bedrock LLM unavailable (%s), using template fallback", error_code)
        explanation = _template_explanation(evidence)
        return {
            "explanation": explanation,
            "source": "template",
            "latency_s": round(elapsed, 2),
            "warning": f"LLM unavailable ({error_code}) — using template explanation",
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.warning("Unexpected error in explanation, using template: %s", e)
        explanation = _template_explanation(evidence)
        return {
            "explanation": explanation,
            "source": "template",
            "latency_s": round(elapsed, 2),
            "warning": f"LLM error — using template explanation: {e}",
        }


def explain_entity(entity_id: str, max_hops: int = 3) -> Dict:
    """Full Tier 2 pipeline: gather evidence then generate explanation.

    This is the main entry point for on-demand explanation in the UI.

    Args:
        entity_id: Account identifier to investigate.
        max_hops: Graph traversal depth.

    Returns:
        Dict with 'evidence', 'explanation', 'source', 'latency_s',
        and optional 'warning'.
    """
    evidence = get_evidence(entity_id, max_hops)
    result = get_explanation(evidence)
    result["evidence"] = evidence
    return result
