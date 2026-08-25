"""Lambda handler for explainability — generates human-readable fraud explanations.

Action Group 3: Explain — Takes graph subgraph data and generates natural language
explanations of why an entity was flagged, with evidence chains.
"""

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GRAPH_ID = os.environ.get("NEPTUNE_GRAPH_ID", "")
REGION = os.environ.get("AWS_REGION", "us-east-1")
SONNET_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"


def get_neptune_client() -> "boto3.client":
    """Create Neptune Analytics data client."""
    session = boto3.Session(region_name=REGION)
    return session.client("neptune-graph")


def get_bedrock_runtime() -> "boto3.client":
    """Create Bedrock Runtime client for LLM calls."""
    session = boto3.Session(region_name=REGION)
    return session.client("bedrock-runtime")


def execute_query(query: str) -> list:
    """Execute openCypher query and return results."""
    client = get_neptune_client()
    graph_id = os.environ.get("NEPTUNE_GRAPH_ID", GRAPH_ID)
    try:
        response = client.execute_query(
            graphIdentifier=graph_id,
            language="OPEN_CYPHER",
            queryString=query,
        )
        payload = json.loads(response["payload"].read())
        return payload.get("results", [])
    except ClientError as e:
        logger.error("Query failed: %s", e)
        return []


def gather_evidence(entity_id: str, max_hops: int = 3) -> dict:
    """Gather evidence subgraph around an entity for explanation.

    Returns structured evidence including:
    - Entity properties
    - Direct relationships
    - Shared device connections
    - Transaction patterns
    - Path to other flagged entities
    """
    evidence = {"entity_id": entity_id, "findings": []}

    # Get entity properties
    entity_query = f"""
        MATCH (n {{`~id`: '{entity_id}'}})
        RETURN n, labels(n) AS type
    """
    entity_results = execute_query(entity_query)
    if entity_results:
        evidence["entity_type"] = entity_results[0].get("type", [])
        evidence["entity_properties"] = entity_results[0].get("n", {})

    # Find shared device connections
    shared_query = f"""
        MATCH (a {{`~id`: '{entity_id}'}})-[:LOGGED_IN_FROM]->(d:Device)<-[:LOGGED_IN_FROM]-(other)
        WHERE a <> other
        RETURN d.`~id` AS device_id, d.device_type AS device_type,
               collect(other.`~id`) AS other_accounts
    """
    shared_results = execute_query(shared_query)
    if shared_results:
        for row in shared_results:
            evidence["findings"].append({
                "type": "shared_device",
                "severity": "high",
                "detail": f"Device {row['device_id']} ({row.get('device_type', 'unknown')}) "
                          f"also accessed by accounts: {', '.join(row['other_accounts'])}",
            })

    # Find KNOWN_ASSOCIATE links
    associate_query = f"""
        MATCH (a {{`~id`: '{entity_id}'}})-[:KNOWN_ASSOCIATE]-(other)
        RETURN other.`~id` AS associate_id, labels(other) AS type
    """
    associate_results = execute_query(associate_query)
    if associate_results:
        for row in associate_results:
            evidence["findings"].append({
                "type": "known_associate",
                "severity": "medium",
                "detail": f"Known associate: {row['associate_id']}",
            })

    # Check transaction patterns
    txn_query = f"""
        MATCH (a {{`~id`: '{entity_id}'}})<-[:INITIATED_BY]-(t:Transaction)-[:PURCHASED_AT]->(m:Merchant)
        RETURN count(t) AS txn_count,
               avg(toFloat(t.amount)) AS avg_amount,
               max(toFloat(t.amount)) AS max_amount,
               collect(DISTINCT m.merchant_name) AS merchants,
               collect(DISTINCT m.risk_tier) AS risk_tiers
    """
    txn_results = execute_query(txn_query)
    if txn_results and txn_results[0]["txn_count"] > 0:
        row = txn_results[0]
        evidence["findings"].append({
            "type": "transaction_pattern",
            "severity": "info",
            "detail": f"{row['txn_count']} transactions, avg ${row['avg_amount']:.2f}, "
                      f"max ${row['max_amount']:.2f}. "
                      f"Merchants: {', '.join(row['merchants'][:5])}. "
                      f"Risk tiers: {', '.join(set(row['risk_tiers']))}",
        })

    # Find broader network via multi-hop
    network_query = f"""
        MATCH path = (start {{`~id`: '{entity_id}'}})-[:SHARED_DEVICE|KNOWN_ASSOCIATE|LOGGED_IN_FROM*1..{max_hops}]-(connected)
        WHERE start <> connected AND connected:Account
        RETURN DISTINCT connected.`~id` AS connected_id,
               length(path) AS hops
        ORDER BY hops
        LIMIT 20
    """
    network_results = execute_query(network_query)
    if network_results:
        evidence["network_size"] = len(network_results)
        evidence["findings"].append({
            "type": "network_reach",
            "severity": "medium" if len(network_results) > 5 else "low",
            "detail": f"Connected to {len(network_results)} accounts within {max_hops} hops "
                      f"via shared devices/associates",
        })

    return evidence


def generate_explanation(evidence: dict) -> str:
    """Generate a natural language explanation from evidence.

    Uses Claude Sonnet via Bedrock for explanation generation.
    Falls back to template-based explanation if Bedrock is unavailable.
    """
    # Build a structured summary for the LLM
    findings_text = "\n".join(
        f"- [{f['severity'].upper()}] {f['type']}: {f['detail']}"
        for f in evidence.get("findings", [])
    )

    prompt = f"""You are a senior fraud analyst. Based on the following evidence from a financial
transaction graph, provide a clear, concise explanation of why entity {evidence['entity_id']}
should be investigated for potential fraud.

Entity Type: {evidence.get('entity_type', 'Unknown')}
Network Size: {evidence.get('network_size', 0)} connected accounts

Findings:
{findings_text}

Provide your analysis in this format:
1. **Summary**: One sentence explaining the key risk
2. **Evidence Chain**: Bullet points tracing the connections that raise concern
3. **Risk Level**: HIGH / MEDIUM / LOW with justification
4. **Recommended Action**: What should the fraud team do next
"""

    try:
        bedrock = get_bedrock_runtime()
        response = bedrock.invoke_model(
            modelId=SONNET_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            }),
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]
    except (ClientError, Exception) as e:
        logger.warning("Bedrock unavailable, using template explanation: %s", e)
        return _template_explanation(evidence)


def _template_explanation(evidence: dict) -> str:
    """Fallback template-based explanation when Bedrock is unavailable."""
    lines = [f"## Investigation Summary: {evidence['entity_id']}\n"]

    high_findings = [f for f in evidence.get("findings", []) if f["severity"] == "high"]
    medium_findings = [f for f in evidence.get("findings", []) if f["severity"] == "medium"]

    if high_findings:
        lines.append("### High-Severity Findings")
        for f in high_findings:
            lines.append(f"- **{f['type']}**: {f['detail']}")

    if medium_findings:
        lines.append("\n### Medium-Severity Findings")
        for f in medium_findings:
            lines.append(f"- **{f['type']}**: {f['detail']}")

    network_size = evidence.get("network_size", 0)
    risk = "HIGH" if high_findings and network_size > 5 else "MEDIUM" if high_findings else "LOW"
    lines.append(f"\n### Risk Level: {risk}")
    lines.append(f"Connected to {network_size} accounts in fraud-indicator network.")

    lines.append("\n### Recommended Action")
    if risk == "HIGH":
        lines.append("- Escalate to fraud investigation team immediately")
        lines.append("- Freeze related accounts pending review")
    elif risk == "MEDIUM":
        lines.append("- Add to enhanced monitoring queue")
        lines.append("- Review transaction history for past 90 days")
    else:
        lines.append("- Continue standard monitoring")

    return "\n".join(lines)


def lambda_handler(event: dict, context: Any) -> dict:
    """Bedrock Agent action group handler for explainability.

    Expected event format:
    {
        "actionGroup": "Explain",
        "function": "explain_entity",
        "parameters": [
            {"name": "entity_id", "value": "A0042"},
            {"name": "max_hops", "value": "3"}
        ]
    }
    """
    logger.info("Event: %s", json.dumps(event))

    function_name = event.get("function", "explain_entity")
    raw_params = event.get("parameters", [])
    params = {p["name"]: p.get("value", "") for p in raw_params}

    if function_name == "explain_entity":
        entity_id = params.get("entity_id", "")
        if not entity_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "entity_id is required"}),
            }
        max_hops = int(params.get("max_hops", 3))

        evidence = gather_evidence(entity_id, max_hops)
        explanation = generate_explanation(evidence)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "entity_id": entity_id,
                "evidence": evidence,
                "explanation": explanation,
            }, default=str),
        }

    if function_name == "gather_evidence":
        entity_id = params.get("entity_id", "")
        max_hops = int(params.get("max_hops", 3))
        evidence = gather_evidence(entity_id, max_hops)
        return {
            "statusCode": 200,
            "body": json.dumps(evidence, default=str),
        }

    return {
        "statusCode": 400,
        "body": json.dumps({"error": f"Unknown function: {function_name}"}),
    }
