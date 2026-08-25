"""Lambda handler for risk scoring based on graph network properties.

Action Group 2: Risk Score — Computes risk based on network topology,
graph algorithms (PageRank, community detection), and relationship analysis.
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


def get_neptune_client() -> "boto3.client":
    """Create Neptune Analytics data client."""
    session = boto3.Session(region_name=REGION)
    return session.client("neptune-graph")


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


def compute_network_risk(account_id: str) -> dict:
    """Compute risk score for an account based on its network properties.

    Risk factors:
    1. Number of shared devices with other accounts (device_sharing_score)
    2. Number of high-risk merchants transacted with (merchant_risk_score)
    3. Connection to known fraud indicators (fraud_proximity_score)
    4. Transaction velocity anomalies (velocity_score)
    """
    # Factor 1: Device sharing
    device_query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})-[:LOGGED_IN_FROM]->(d:Device)<-[:LOGGED_IN_FROM]-(other:Account)
        WHERE a <> other
        RETURN count(DISTINCT other) AS shared_account_count,
               count(DISTINCT d) AS shared_device_count
    """
    device_results = execute_query(device_query)
    shared_accounts = device_results[0]["shared_account_count"] if device_results else 0
    shared_devices = device_results[0]["shared_device_count"] if device_results else 0
    device_sharing_score = min(shared_accounts * 0.15 + shared_devices * 0.1, 1.0)

    # Factor 2: High-risk merchant exposure
    merchant_query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})<-[:INITIATED_BY]-(t:Transaction)-[:PURCHASED_AT]->(m:Merchant)
        WHERE m.risk_tier IN ['high', 'critical']
        RETURN count(DISTINCT m) AS high_risk_merchants,
               count(t) AS high_risk_txns
    """
    merchant_results = execute_query(merchant_query)
    high_risk_merchants = merchant_results[0]["high_risk_merchants"] if merchant_results else 0
    high_risk_txns = merchant_results[0]["high_risk_txns"] if merchant_results else 0
    merchant_risk_score = min(high_risk_merchants * 0.2 + high_risk_txns * 0.05, 1.0)

    # Factor 3: Proximity to SHARED_DEVICE or KNOWN_ASSOCIATE edges (fraud indicators)
    proximity_query = f"""
        MATCH path = (a:Account {{`~id`: '{account_id}'}})-[:SHARED_DEVICE|KNOWN_ASSOCIATE*1..3]-(connected)
        WHERE a <> connected
        RETURN count(DISTINCT connected) AS connected_entities,
               min(length(path)) AS min_distance
    """
    proximity_results = execute_query(proximity_query)
    connected_entities = proximity_results[0]["connected_entities"] if proximity_results else 0
    min_distance = proximity_results[0]["min_distance"] if proximity_results else 999
    fraud_proximity_score = min(connected_entities * 0.1 / max(min_distance, 1), 1.0)

    # Factor 4: Transaction velocity
    velocity_query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})<-[:INITIATED_BY]-(t:Transaction)
        RETURN count(t) AS txn_count,
               avg(toFloat(t.amount)) AS avg_amount,
               max(toFloat(t.amount)) AS max_amount
    """
    velocity_results = execute_query(velocity_query)
    txn_count = velocity_results[0]["txn_count"] if velocity_results else 0
    avg_amount = velocity_results[0]["avg_amount"] if velocity_results else 0
    max_amount = velocity_results[0]["max_amount"] if velocity_results else 0
    velocity_score = min(txn_count * 0.02, 1.0) if txn_count > 15 else 0.0

    # Weighted composite score
    composite = (
        device_sharing_score * 0.35
        + merchant_risk_score * 0.20
        + fraud_proximity_score * 0.30
        + velocity_score * 0.15
    )

    # Confidence based on data availability
    confidence = "high" if txn_count > 5 else "medium" if txn_count > 0 else "low"

    return {
        "account_id": account_id,
        "risk_score": round(composite, 4),
        "risk_level": "high" if composite > 0.6 else "medium" if composite > 0.3 else "low",
        "confidence": confidence,
        "factors": {
            "device_sharing": {
                "score": round(device_sharing_score, 4),
                "weight": 0.35,
                "detail": f"{shared_accounts} shared accounts via {shared_devices} devices",
            },
            "merchant_risk": {
                "score": round(merchant_risk_score, 4),
                "weight": 0.20,
                "detail": f"{high_risk_txns} txns at {high_risk_merchants} high-risk merchants",
            },
            "fraud_proximity": {
                "score": round(fraud_proximity_score, 4),
                "weight": 0.30,
                "detail": f"{connected_entities} entities within 3 hops via fraud edges",
            },
            "velocity": {
                "score": round(velocity_score, 4),
                "weight": 0.15,
                "detail": f"{txn_count} txns, avg ${avg_amount:.2f}, max ${max_amount:.2f}",
            },
        },
    }


def lambda_handler(event: dict, context: Any) -> dict:
    """Bedrock Agent action group handler for risk scoring.

    Expected event format:
    {
        "actionGroup": "RiskScore",
        "function": "compute_risk",
        "parameters": [
            {"name": "account_id", "value": "A0042"}
        ]
    }
    """
    logger.info("Event: %s", json.dumps(event))

    function_name = event.get("function", "compute_risk")
    raw_params = event.get("parameters", [])
    params = {p["name"]: p.get("value", "") for p in raw_params}

    if function_name == "compute_risk":
        account_id = params.get("account_id", "")
        if not account_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "account_id is required"}),
            }
        result = compute_network_risk(account_id)
        return {
            "statusCode": 200,
            "body": json.dumps(result, default=str),
        }

    return {
        "statusCode": 400,
        "body": json.dumps({"error": f"Unknown function: {function_name}"}),
    }
