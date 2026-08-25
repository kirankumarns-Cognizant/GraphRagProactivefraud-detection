"""Warmup module — pre-verify persona accounts exist in Neptune.

Queries the graph for each persona account to confirm it has the expected
relationships and properties. This catches stale data before the demo starts.
"""

import json
import logging
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError

from streamlit_app.config.settings import NEPTUNE_GRAPH_ID, PERSONAS, REGION

logger = logging.getLogger(__name__)


def _execute_query(query: str) -> list:
    """Execute an openCypher query against Neptune Analytics."""
    try:
        client = boto3.Session(region_name=REGION).client("neptune-graph")
        response = client.execute_query(
            graphIdentifier=NEPTUNE_GRAPH_ID,
            language="OPEN_CYPHER",
            queryString=query,
        )
        payload = json.loads(response["payload"].read())
        return payload.get("results", [])
    except (ClientError, Exception) as e:
        logger.error("Warmup query failed: %s", e)
        return []


def verify_persona(account_id: str) -> Dict:
    """Verify a persona account exists and has graph relationships.

    Returns:
        Dict with account_id, exists, node_count, edge_info.
    """
    # Check account node exists
    node_query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})
        RETURN a.`~id` AS id, labels(a) AS labels
    """
    node_results = _execute_query(node_query)

    if not node_results:
        return {
            "account_id": account_id,
            "exists": False,
            "detail": "Account not found in graph",
        }

    # Check relationships
    rel_query = f"""
        MATCH (a:Account {{`~id`: '{account_id}'}})-[r]-(connected)
        RETURN type(r) AS rel_type, count(*) AS count
    """
    rel_results = _execute_query(rel_query)
    relationships = {r["rel_type"]: r["count"] for r in rel_results} if rel_results else {}

    return {
        "account_id": account_id,
        "exists": True,
        "relationships": relationships,
        "total_connections": sum(relationships.values()),
        "detail": f"Found with {sum(relationships.values())} connections",
    }


def warmup_all_personas() -> Dict[str, Dict]:
    """Verify all persona accounts and return results.

    Returns:
        Dict mapping persona key to verification result.
    """
    results = {}
    for key, persona in PERSONAS.items():
        account_id = persona["account_id"]
        result = verify_persona(account_id)
        result["persona_name"] = persona["name"]
        results[key] = result
        logger.info(
            "Warmup %s (%s): %s",
            persona["name"],
            account_id,
            "OK" if result["exists"] else "MISSING",
        )
    return results
