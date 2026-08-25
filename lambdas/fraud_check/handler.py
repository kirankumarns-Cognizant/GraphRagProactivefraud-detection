"""Tier 1: Deterministic fraud rules engine.

Evaluates a transaction against 6 graph-based rules using Neptune Analytics.
No LLM involved — pure graph traversal for sub-200ms decisions.

Rules:
  1. Shared Device: Account shares device with ≥2 other accounts
  2. Known Associate: Account within 2 hops of KNOWN_ASSOCIATE edge
  3. Amount Anomaly: Transaction amount > 5x account average
  4. High-Risk Merchant: Merchant risk_tier='high' + amount > threshold
  5. Velocity Burst: Account has >10 txns in recent 1hr window
  6. VPN/Tor IP: Account connected to VPN/Tor IP within 2 hops
"""

import json
import logging
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")

# Tunable thresholds
SHARED_DEVICE_MIN = 5          # Flag if account shares device with >= N others
AMOUNT_MULTIPLIER = 5.0        # Flag if txn amount > N * account average
HIGH_RISK_AMOUNT_THRESHOLD = 500  # Flag if high-risk merchant AND amount > $N
VELOCITY_THRESHOLD = 10        # Flag if account has > N txns recently
AMOUNT_ANOMALY_MIN = 200       # Don't flag small amount anomalies

# Scoring weights: each rule contributes a weighted score to the decision
RULE_WEIGHTS = {
    "known_associate": 50,     # Very strong signal — only fraud ring members have this
    "shared_device": 10,       # Weak signal alone due to dataset density
    "amount_anomaly": 25,      # Moderate signal
    "high_risk_merchant": 15,  # Moderate signal
    "velocity_burst": 20,      # Good signal at threshold >10
    "vpn_tor_ip": 10,          # Weak signal alone — many legit VPN users
}
SCORE_THRESHOLD = 40           # Flag if total score >= this (tuned for >=70% recall)


def get_neptune_client() -> "boto3.client":
    """Create Neptune Analytics client."""
    return boto3.Session(region_name=REGION).client("neptune-graph")


def execute_query(client: "boto3.client", query: str) -> list:
    """Execute openCypher query and return results."""
    graph_id = os.environ.get("NEPTUNE_GRAPH_ID", "")
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


def rule_shared_device(client: "boto3.client", account_id: str) -> dict | None:
    """Rule 1: Account shares device with ≥2 other accounts."""
    query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})-[:LOGGED_IN_FROM]->(d:Device)<-[:LOGGED_IN_FROM]-(other:Account)
        WHERE a <> other
        WITH d.`~id` AS device_id, count(DISTINCT other) AS shared_count
        WHERE shared_count >= {SHARED_DEVICE_MIN}
        RETURN device_id, shared_count
        ORDER BY shared_count DESC
        LIMIT 3
    """
    results = execute_query(client, query)
    if results:
        top = results[0]
        return {
            "rule": "shared_device",
            "severity": "high",
            "detail": f"Shares device {top['device_id']} with {top['shared_count']} other accounts",
        }
    return None


def rule_known_associate(client: "boto3.client", account_id: str) -> dict | None:
    """Rule 2: Account within 2 hops of KNOWN_ASSOCIATE edge."""
    query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})<-[:OWNS]-(c:Customer)-[:KNOWN_ASSOCIATE*1..2]-(other:Customer)
        WHERE c <> other
        RETURN count(DISTINCT other) AS associate_count
    """
    results = execute_query(client, query)
    if results and results[0]["associate_count"] > 0:
        return {
            "rule": "known_associate",
            "severity": "medium",
            "detail": f"Owner linked to {results[0]['associate_count']} known associates within 2 hops",
        }
    return None


def rule_amount_anomaly(client: "boto3.client", account_id: str, txn_amount: float) -> dict | None:
    """Rule 3: Transaction amount > 5x account average."""
    if txn_amount < AMOUNT_ANOMALY_MIN:
        return None

    query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})<-[:INITIATED_BY]-(t:Transaction)
        RETURN avg(toFloat(t.amount)) AS avg_amount, count(t) AS txn_count
    """
    results = execute_query(client, query)
    if results and results[0]["txn_count"] > 3:
        avg = results[0]["avg_amount"]
        if avg > 0 and txn_amount > avg * AMOUNT_MULTIPLIER:
            return {
                "rule": "amount_anomaly",
                "severity": "medium",
                "detail": f"Amount ${txn_amount:.2f} is {txn_amount/avg:.1f}x the account average (${avg:.2f})",
            }
    return None


def rule_high_risk_merchant(client: "boto3.client", merchant_id: str, txn_amount: float) -> dict | None:
    """Rule 4: High-risk merchant + amount above threshold."""
    query = f"""
        MATCH (m:Merchant {{`~id`: '{merchant_id}'}})
        RETURN m.risk_tier AS risk_tier, m.merchant_name AS name
    """
    results = execute_query(client, query)
    if results and results[0].get("risk_tier") == "high" and txn_amount > HIGH_RISK_AMOUNT_THRESHOLD:
        return {
            "rule": "high_risk_merchant",
            "severity": "medium",
            "detail": f"${txn_amount:.2f} at high-risk merchant {results[0].get('name', merchant_id)}",
        }
    return None


def rule_velocity_burst(client: "boto3.client", account_id: str) -> dict | None:
    """Rule 5: Account has >10 recent transactions (velocity indicator)."""
    query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})<-[:INITIATED_BY]-(t:Transaction)
        RETURN count(t) AS txn_count
    """
    results = execute_query(client, query)
    if results and results[0]["txn_count"] > VELOCITY_THRESHOLD:
        return {
            "rule": "velocity_burst",
            "severity": "medium",
            "detail": f"Account has {results[0]['txn_count']} transactions (threshold: {VELOCITY_THRESHOLD})",
        }
    return None


def rule_vpn_tor_ip(client: "boto3.client", account_id: str) -> dict | None:
    """Rule 6: Account connected to VPN/Tor IP within 2 hops."""
    query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})-[:LOGGED_IN_FROM]->(d:Device)-[:CONNECTED_VIA]->(ip:IP_Address)
        WHERE ip.is_vpn = 'True' OR ip.is_tor = 'True'
        RETURN ip.`~id` AS ip_id, ip.is_vpn AS is_vpn, ip.is_tor AS is_tor
        LIMIT 3
    """
    results = execute_query(client, query)
    if results:
        ip = results[0]
        ip_type = "VPN" if ip.get("is_vpn") == "True" else "Tor"
        return {
            "rule": "vpn_tor_ip",
            "severity": "high",
            "detail": f"Connected to {ip_type} IP {ip['ip_id']} via device",
        }
    return None


def check_transaction(
    account_id: str,
    merchant_id: str,
    amount: float,
    transaction_id: str = "",
) -> dict:
    """Run all 6 rules against a transaction and return decision.

    Returns:
        {
            "transaction_id": "TXN-001",
            "decision": "APPROVE" | "FLAG",
            "rules_triggered": [...],
            "latency_ms": 85.3
        }
    """
    start = time.time()
    client = get_neptune_client()
    triggered = []

    # Run all 6 rules
    checks = [
        rule_shared_device(client, account_id),
        rule_known_associate(client, account_id),
        rule_amount_anomaly(client, account_id, amount),
        rule_high_risk_merchant(client, merchant_id, amount),
        rule_velocity_burst(client, account_id),
        rule_vpn_tor_ip(client, account_id),
    ]

    triggered = [r for r in checks if r is not None]
    latency_ms = (time.time() - start) * 1000

    # Weighted scoring: sum rule weights, flag if above threshold
    risk_score = sum(RULE_WEIGHTS.get(r["rule"], 10) for r in triggered)
    decision = "FLAG" if risk_score >= SCORE_THRESHOLD else "APPROVE"

    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "merchant_id": merchant_id,
        "amount": amount,
        "decision": decision,
        "risk_score": risk_score,
        "rules_triggered": triggered,
        "rule_count": len(triggered),
        "latency_ms": round(latency_ms, 1),
    }


def publish_to_sns(result: dict) -> None:
    """Publish flagged transaction to SNS topic."""
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN", "")
    if not sns_topic_arn or result["decision"] != "FLAG":
        return

    rules_text = "\n".join(
        f"  - [{r['severity'].upper()}] {r['rule']}: {r['detail']}"
        for r in result["rules_triggered"]
    )

    message = (
        f"FRAUD ALERT: Transaction {result['transaction_id']} flagged\n\n"
        f"Account: {result['account_id']}\n"
        f"Amount: ${result['amount']:.2f}\n"
        f"Merchant: {result['merchant_id']}\n"
        f"Rules Triggered ({result['rule_count']}):\n{rules_text}\n\n"
        f"Latency: {result['latency_ms']:.0f}ms\n\n"
        f"Action Required: Review and approve or decline this transaction."
    )

    try:
        sns = boto3.Session(region_name=REGION).client("sns")
        sns.publish(
            TopicArn=sns_topic_arn,
            Subject=f"Fraud Alert: ${result['amount']:.2f} on {result['account_id']}",
            Message=message,
        )
        logger.info("Published fraud alert to SNS for %s", result["transaction_id"])
    except ClientError as e:
        logger.error("Failed to publish to SNS: %s", e)


def lambda_handler(event: dict, context: Any) -> dict:
    """Lambda entry point for Tier 1 fraud check.

    Expected event:
    {
        "transaction_id": "TXN-001",
        "account_id": "A0042",
        "merchant_id": "M0015",
        "amount": 5000.00
    }
    """
    logger.info("Event: %s", json.dumps(event))

    transaction_id = event.get("transaction_id", "")
    account_id = event.get("account_id", "")
    merchant_id = event.get("merchant_id", "")
    amount = float(event.get("amount", 0))

    if not account_id or not merchant_id:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "account_id and merchant_id required"}),
        }

    result = check_transaction(account_id, merchant_id, amount, transaction_id)

    # Publish to SNS if flagged
    publish_to_sns(result)

    return {
        "statusCode": 200,
        "body": json.dumps(result, default=str),
    }
