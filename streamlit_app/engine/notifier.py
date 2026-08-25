"""Notification engine wrapper — SNS alerts for REVIEW transactions.

Publishes fraud alert messages to the existing SNS topic when a transaction
is classified as REVIEW. Failures are logged but never block the transaction flow.
"""

import logging
import os
import sys
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# Ensure project root is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from streamlit_app.config.settings import REGION, SNS_TOPIC_NAME

logger = logging.getLogger(__name__)


def _get_topic_arn() -> Optional[str]:
    """Look up the SNS topic ARN by name.

    Returns:
        Topic ARN string, or None if not found.
    """
    try:
        sns = boto3.Session(region_name=REGION).client("sns")
        topics = sns.list_topics().get("Topics", [])
        fraud_topics = [t for t in topics if SNS_TOPIC_NAME in t["TopicArn"]]
        return fraud_topics[0]["TopicArn"] if fraud_topics else None
    except (ClientError, NoCredentialsError, Exception) as e:
        logger.error("Failed to look up SNS topic: %s", e)
        return None


def send_review_notification(result: Dict) -> Dict:
    """Send an SNS notification for a REVIEW transaction.

    Only sends if the decision is REVIEW. Failures are captured
    but never block the calling code.

    Args:
        result: Transaction scoring result from score_transaction().

    Returns:
        Dict with 'sent' (bool), 'message_id' (str or None),
        'error' (str or None).
    """
    # Only notify for REVIEW decisions
    if result.get("decision") != "REVIEW":
        return {"sent": False, "message_id": None, "error": None,
                "reason": f"Decision is {result.get('decision')}, not REVIEW"}

    topic_arn = _get_topic_arn()
    if not topic_arn:
        return {"sent": False, "message_id": None,
                "error": "SNS topic not found"}

    # Build notification message
    rules_text = "\n".join(
        f"  - [{r['severity'].upper()}] {r['rule']}: {r['detail']}"
        for r in result.get("rules_triggered", [])
    ) or "  (No specific rules triggered — score defaulted to REVIEW)"

    warnings_text = ""
    if result.get("warnings"):
        warnings_text = "\n\nWarnings:\n" + "\n".join(
            f"  - {w}" for w in result["warnings"]
        )

    message = (
        f"TRANSACTION REVIEW REQUIRED\n"
        f"{'=' * 40}\n\n"
        f"Transaction: {result.get('transaction_id', 'N/A')}\n"
        f"Account: {result.get('account_id', 'N/A')}\n"
        f"Amount: ${result.get('amount', 0):.2f}\n"
        f"Merchant: {result.get('merchant_id', 'N/A')}\n"
        f"Risk Score: {result.get('risk_score', 0)}\n"
        f"Decision: REVIEW (score {result.get('risk_score', 0)} in range 30-59)\n\n"
        f"Rules Triggered ({result.get('rule_count', 0)}):\n{rules_text}"
        f"{warnings_text}\n\n"
        f"Action Required: Approve or reject this transaction.\n"
        f"{'=' * 40}\n"
        f"GraphRAG Fraud Detection POC"
    )

    subject = (
        f"Review Required: ${result.get('amount', 0):.2f} "
        f"on {result.get('account_id', '?')}"
    )

    try:
        sns = boto3.Session(region_name=REGION).client("sns")
        response = sns.publish(
            TopicArn=topic_arn,
            Subject=subject[:100],  # SNS subject max 100 chars
            Message=message,
        )
        message_id = response.get("MessageId", "unknown")
        logger.info("SNS notification sent: %s", message_id)
        return {"sent": True, "message_id": message_id, "error": None}

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.error("SNS publish failed: %s", e)
        return {"sent": False, "message_id": None,
                "error": f"SNS publish failed ({error_code})"}

    except Exception as e:
        logger.error("Unexpected SNS error: %s", e)
        return {"sent": False, "message_id": None,
                "error": f"SNS error: {e}"}
