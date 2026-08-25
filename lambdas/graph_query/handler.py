"""Lambda handler for Neptune Analytics graph queries.

Action Group 1: Graph Query — Executes openCypher graph traversal queries on Neptune Analytics.
Supports multi-hop fraud ring detection, path exploration, and entity lookups.
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

# Pre-built openCypher query templates for fraud detection
QUERY_TEMPLATES = {
    "entity_lookup": """
        MATCH (n {{{id_field}: $entity_id}})
        RETURN n
    """,
    "multi_hop": """
        MATCH path = (start {{~id: $entity_id}})-[*1..{max_hops}]-(connected)
        WHERE start <> connected
        RETURN DISTINCT connected.`~id` AS id, labels(connected) AS type,
               length(path) AS hops
        ORDER BY hops
        LIMIT $limit
    """,
    "shared_devices": """
        MATCH (a1:Account)-[:LOGGED_IN_FROM]->(d:Device)<-[:LOGGED_IN_FROM]-(a2:Account)
        WHERE a1.`~id` <> a2.`~id`
        RETURN d.`~id` AS device_id, collect(DISTINCT a1.`~id`) + collect(DISTINCT a2.`~id`) AS accounts,
               count(DISTINCT a1) + count(DISTINCT a2) AS account_count
        ORDER BY account_count DESC
    """,
    "account_network": """
        MATCH (a:Account {{`~id`: $account_id}})
        OPTIONAL MATCH (a)-[:LOGGED_IN_FROM]->(d:Device)
        OPTIONAL MATCH (a)<-[:INITIATED_BY]-(t:Transaction)-[:PURCHASED_AT]->(m:Merchant)
        OPTIONAL MATCH (d)<-[:LOGGED_IN_FROM]-(other:Account)
        WHERE other.`~id` <> a.`~id`
        RETURN a.`~id` AS account,
               collect(DISTINCT d.`~id`) AS devices,
               collect(DISTINCT m.`~id`) AS merchants,
               collect(DISTINCT other.`~id`) AS shared_accounts,
               count(DISTINCT t) AS transaction_count
    """,
    "fraud_ring_members": """
        MATCH (start {{`~id`: $entity_id}})
        MATCH path = (start)-[:LOGGED_IN_FROM|SHARED_DEVICE|KNOWN_ASSOCIATE*1..{max_hops}]-(member)
        WHERE start <> member
        RETURN DISTINCT member.`~id` AS member_id, labels(member) AS member_type,
               length(path) AS distance
        ORDER BY distance
    """,
    "path_between": """
        MATCH path = shortestPath(
            (a {{`~id`: $entity_a}})-[*..{max_hops}]-(b {{`~id`: $entity_b}})
        )
        RETURN [n IN nodes(path) | n.`~id`] AS node_ids,
               [n IN nodes(path) | labels(n)] AS node_types,
               [r IN relationships(path) | type(r)] AS edge_types,
               length(path) AS path_length
    """,
    "transaction_velocity": """
        MATCH (a:Account {{`~id`: $account_id}})<-[:INITIATED_BY]-(t:Transaction)
        WITH a, t ORDER BY t.timestamp
        WITH a, collect(t) AS txns
        RETURN a.`~id` AS account_id,
               size(txns) AS total_txns,
               head(txns).timestamp AS first_txn,
               last(txns).timestamp AS last_txn
    """,
}


def get_neptune_client() -> "boto3.client":
    """Create Neptune Analytics data client."""
    session = boto3.Session(region_name=REGION)
    return session.client("neptune-graph")


def execute_query(query: str, parameters: dict[str, Any] | None = None) -> dict:
    """Execute an openCypher query against Neptune Analytics."""
    client = get_neptune_client()

    kwargs: dict[str, Any] = {
        "graphIdentifier": GRAPH_ID,
        "language": "OPEN_CYPHER",
        "queryString": query,
    }
    if parameters:
        kwargs["parameters"] = json.dumps(parameters)

    try:
        # Note: Neptune Analytics uses 'queryString' not 'query'
        response = client.execute_query(**kwargs)
        # Response payload is a streaming body
        payload = json.loads(response["payload"].read())
        return {"status": "success", "results": payload.get("results", [])}
    except ClientError as e:
        logger.error("Query failed: %s", e)
        return {"status": "error", "message": str(e)}


def handle_entity_lookup(params: dict) -> dict:
    """Look up an entity by ID."""
    entity_id = params["entity_id"]
    query = f"MATCH (n {{`~id`: '{entity_id}'}}) RETURN n LIMIT 1"
    return execute_query(query)


def handle_multi_hop(params: dict) -> dict:
    """Find all entities within N hops of a starting entity."""
    entity_id = params["entity_id"]
    max_hops = params.get("max_hops", 3)
    limit = params.get("limit", 50)
    query = f"""
        MATCH path = (start {{`~id`: '{entity_id}'}})-[*1..{max_hops}]-(connected)
        WHERE start <> connected
        RETURN DISTINCT connected.`~id` AS id, labels(connected) AS type,
               length(path) AS hops
        ORDER BY hops
        LIMIT {limit}
    """
    return execute_query(query)


def handle_shared_devices(params: dict) -> dict:
    """Find devices shared between multiple accounts."""
    return execute_query(QUERY_TEMPLATES["shared_devices"])


def handle_account_network(params: dict) -> dict:
    """Get the full network of an account (devices, merchants, connected accounts)."""
    account_id = params["account_id"]
    query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})
        OPTIONAL MATCH (a)-[:LOGGED_IN_FROM]->(d:Device)
        OPTIONAL MATCH (a)<-[:INITIATED_BY]-(t:Transaction)-[:PURCHASED_AT]->(m:Merchant)
        OPTIONAL MATCH (d)<-[:LOGGED_IN_FROM]-(other:Account)
        WHERE other.`~id` <> a.`~id`
        RETURN a.`~id` AS account,
               collect(DISTINCT d.`~id`) AS devices,
               collect(DISTINCT m.`~id`) AS merchants,
               collect(DISTINCT other.`~id`) AS shared_accounts,
               count(DISTINCT t) AS transaction_count
    """
    return execute_query(query)


def handle_fraud_ring(params: dict) -> dict:
    """Find potential fraud ring members from a starting entity."""
    entity_id = params["entity_id"]
    max_hops = params.get("max_hops", 3)
    query = f"""
        MATCH (start {{`~id`: '{entity_id}'}})
        MATCH path = (start)-[:LOGGED_IN_FROM|SHARED_DEVICE|KNOWN_ASSOCIATE*1..{max_hops}]-(member)
        WHERE start <> member
        RETURN DISTINCT member.`~id` AS member_id, labels(member) AS member_type,
               length(path) AS distance
        ORDER BY distance
    """
    return execute_query(query)


def handle_shortest_path(params: dict) -> dict:
    """Find the shortest path between two entities.

    Neptune Analytics doesn't support shortestPath(), so we incrementally
    search at increasing hop distances.
    """
    entity_a = params["entity_a"]
    entity_b = params["entity_b"]
    max_hops = params.get("max_hops", 6)

    for hops in range(1, max_hops + 1):
        query = f"""
            MATCH (a {{`~id`: '{entity_a}'}})-[*{hops}]-(b {{`~id`: '{entity_b}'}})
            RETURN {hops} AS path_length
            LIMIT 1
        """
        result = execute_query(query)
        if result.get("results"):
            return {
                "status": "success",
                "results": [{
                    "entity_a": entity_a,
                    "entity_b": entity_b,
                    "path_length": hops,
                }],
            }

    return {"status": "success", "results": [], "message": f"No path found within {max_hops} hops"}


# Action routing table
ACTION_HANDLERS = {
    "entity_lookup": handle_entity_lookup,
    "multi_hop": handle_multi_hop,
    "shared_devices": handle_shared_devices,
    "account_network": handle_account_network,
    "fraud_ring": handle_fraud_ring,
    "shortest_path": handle_shortest_path,
}


def lambda_handler(event: dict, context: Any) -> dict:
    """Bedrock Agent action group handler for graph queries.

    Expected event format (Bedrock Agent action group):
    {
        "actionGroup": "GraphQuery",
        "function": "multi_hop",
        "parameters": [
            {"name": "entity_id", "value": "A0042"},
            {"name": "max_hops", "value": "3"}
        ]
    }
    """
    logger.info("Event: %s", json.dumps(event))

    # Parse Bedrock Agent event format
    function_name = event.get("function", "")
    raw_params = event.get("parameters", [])

    # Convert Bedrock param list to dict
    params = {}
    for p in raw_params:
        params[p["name"]] = p.get("value", "")

    # Try to convert numeric params
    for key in ("max_hops", "limit"):
        if key in params:
            try:
                params[key] = int(params[key])
            except (ValueError, TypeError):
                pass

    handler = ACTION_HANDLERS.get(function_name)
    if not handler:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": f"Unknown function: {function_name}",
                "available": list(ACTION_HANDLERS.keys()),
            }),
        }

    try:
        result = handler(params)
        return {
            "statusCode": 200,
            "body": json.dumps(result, default=str),
        }
    except Exception as e:
        logger.error("Handler %s failed: %s", function_name, e, exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
