"""Health check component — verifies AWS service connectivity.

Checks Neptune Analytics, SNS topic, and Bedrock model access.
Returns status indicators for the Streamlit sidebar.
"""

import json
import logging
from typing import Tuple

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from streamlit_app.config.settings import (
    NEPTUNE_GRAPH_ID,
    REGION,
    SNS_TOPIC_NAME,
    SONNET_MODEL_ID,
)

logger = logging.getLogger(__name__)


def _get_session() -> boto3.Session:
    """Create a boto3 session for the configured region."""
    return boto3.Session(region_name=REGION)


def check_neptune() -> Tuple[str, str]:
    """Verify Neptune Analytics graph is reachable.

    Returns:
        Tuple of (status, detail) where status is 'green', 'amber', or 'red'.
    """
    try:
        client = _get_session().client("neptune-graph")
        resp = client.get_graph(graphIdentifier=NEPTUNE_GRAPH_ID)
        status = resp.get("status", "UNKNOWN")
        if status == "AVAILABLE":
            return "green", f"Graph {NEPTUNE_GRAPH_ID} — AVAILABLE"
        return "amber", f"Graph {NEPTUNE_GRAPH_ID} — {status}"
    except ClientError as e:
        code = e.response["Error"]["Code"]
        return "red", f"Neptune error: {code}"
    except NoCredentialsError:
        return "red", "No AWS credentials configured"
    except Exception as e:
        return "red", f"Neptune unreachable: {e}"


def check_neptune_data() -> Tuple[str, str]:
    """Verify Neptune graph has data (run a simple count query).

    Returns:
        Tuple of (status, detail).
    """
    try:
        client = _get_session().client("neptune-graph")
        response = client.execute_query(
            graphIdentifier=NEPTUNE_GRAPH_ID,
            language="OPEN_CYPHER",
            queryString="MATCH (n) RETURN count(n) AS node_count LIMIT 1",
        )
        payload = json.loads(response["payload"].read())
        results = payload.get("results", [])
        if results and results[0].get("node_count", 0) > 0:
            count = results[0]["node_count"]
            return "green", f"{count} nodes in graph"
        return "amber", "Graph is empty — no nodes found"
    except Exception as e:
        return "red", f"Query failed: {e}"


def check_sns() -> Tuple[str, str]:
    """Verify SNS fraud alert topic exists and has subscriptions.

    Returns:
        Tuple of (status, detail).
    """
    try:
        sns = _get_session().client("sns")
        topics = sns.list_topics().get("Topics", [])
        fraud_topics = [t for t in topics if SNS_TOPIC_NAME in t["TopicArn"]]
        if not fraud_topics:
            return "amber", f"Topic '{SNS_TOPIC_NAME}' not found"
        topic_arn = fraud_topics[0]["TopicArn"]
        subs = sns.list_subscriptions_by_topic(TopicArn=topic_arn)
        sub_count = len(subs.get("Subscriptions", []))
        return "green", f"Topic active — {sub_count} subscription(s)"
    except NoCredentialsError:
        return "red", "No AWS credentials configured"
    except Exception as e:
        return "red", f"SNS error: {e}"


def check_bedrock() -> Tuple[str, str]:
    """Verify Bedrock model access for Tier 2 explanations.

    Returns:
        Tuple of (status, detail).
    """
    try:
        bedrock = _get_session().client("bedrock-runtime")
        # Minimal test: invoke with tiny prompt
        response = bedrock.invoke_model(
            modelId=SONNET_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Say OK"}],
            }),
        )
        result = json.loads(response["body"].read())
        if result.get("content"):
            return "green", "Claude Sonnet 4 — accessible"
        return "amber", "Bedrock responded but no content"
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if "AccessDeniedException" in code:
            return "amber", "Bedrock access pending — Tier 2 will use fallback"
        return "red", f"Bedrock error: {code}"
    except NoCredentialsError:
        return "red", "No AWS credentials configured"
    except Exception as e:
        return "amber", f"Bedrock unavailable — Tier 2 will use fallback: {e}"


def run_all_checks() -> dict:
    """Run all health checks and return results.

    Returns:
        Dict mapping service name to (status, detail) tuples.
    """
    return {
        "Neptune Graph": check_neptune(),
        "Neptune Data": check_neptune_data(),
        "SNS Alerts": check_sns(),
        "Bedrock LLM": check_bedrock(),
    }
