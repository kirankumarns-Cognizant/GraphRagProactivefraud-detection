#!/usr/bin/env python3
"""Run graph algorithms on Neptune Analytics to validate fraud detection.

M2, Task 2.5 — Runs:
1. Community detection (Louvain) to find clusters
2. PageRank to find high-influence nodes
3. Shortest path between known fraud entities
4. Node/edge count validation

Requires: Neptune Analytics graph in AVAILABLE state.
"""

import json
import logging

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGION = "us-east-1"
GRAPH_ID = "g-a6z57uuv00"


def execute_query(neptune_client: "boto3.client", query: str) -> list:
    """Execute openCypher query and return results."""
    try:
        response = neptune_client.execute_query(
            graphIdentifier=GRAPH_ID,
            language="OPEN_CYPHER",
            queryString=query,
        )
        payload = json.loads(response["payload"].read())
        return payload.get("results", [])
    except ClientError as e:
        logger.error("Query failed: %s\nQuery: %s", e, query)
        return []


def validate_node_counts(neptune: "boto3.client") -> dict:
    """T2.1: Validate node counts match generated data."""
    logger.info("=== T2.1: Node Count Validation ===")

    expected = {
        "Customer": 100,
        "Account": 150,
        "Device": 50,
        "Merchant": 30,
        "IP_Address": 20,
        "Transaction": 1364,
    }

    results = {}
    total = 0
    for label, exp_count in expected.items():
        query = f"MATCH (n:{label}) RETURN count(n) AS cnt"
        rows = execute_query(neptune, query)
        actual = rows[0]["cnt"] if rows else 0
        status = "PASS" if actual == exp_count else "FAIL"
        results[label] = {"expected": exp_count, "actual": actual, "status": status}
        total += actual
        logger.info("  %s: %d / %d [%s]", label, actual, exp_count, status)

    results["total"] = {"expected": 1714, "actual": total, "status": "PASS" if total == 1714 else "FAIL"}
    logger.info("  TOTAL: %d / 1714 [%s]", total, results["total"]["status"])
    return results


def validate_edge_counts(neptune: "boto3.client") -> dict:
    """T2.2: Validate edge counts."""
    logger.info("\n=== T2.2: Edge Count Validation ===")

    expected = {
        "LOGGED_IN_FROM": 300,
        "SHARED_DEVICE": 84,
        "KNOWN_ASSOCIATE": 35,
        "INITIATED_BY": 1364,
        "PURCHASED_AT": 1364,
        "OWNS": 150,
        "CONNECTED_VIA": 50,
    }

    results = {}
    total = 0
    for rel_type, exp_count in expected.items():
        query = f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS cnt"
        rows = execute_query(neptune, query)
        actual = rows[0]["cnt"] if rows else 0
        status = "PASS" if actual == exp_count else "CLOSE" if abs(actual - exp_count) < 10 else "FAIL"
        results[rel_type] = {"expected": exp_count, "actual": actual, "status": status}
        total += actual
        logger.info("  %s: %d / %d [%s]", rel_type, actual, exp_count, status)

    results["total"] = {"expected": 3347, "actual": total}
    logger.info("  TOTAL: %d / 3347", total)
    return results


def run_community_detection(neptune: "boto3.client") -> list:
    """T2.3: Run community detection to find fraud clusters.

    Neptune Analytics supports graph algorithms via CALL procedures.
    """
    logger.info("\n=== T2.3: Community Detection ===")

    # Neptune Analytics community detection
    # Using connected components as a simpler alternative if Louvain isn't available
    query = """
        CALL neptune.algo.community.louvain(
            {writeProperty: 'community'}
        )
        YIELD node, communityId
        WITH communityId, collect(node.`~id`) AS members, count(*) AS size
        WHERE size > 2
        RETURN communityId, size, members[..10] AS sample_members
        ORDER BY size DESC
        LIMIT 20
    """
    results = execute_query(neptune, query)

    if not results:
        logger.warning("Louvain not available, trying connected components approach...")
        # Fallback: find clusters via shared device connections
        query = """
            MATCH (a1:Account)-[:LOGGED_IN_FROM]->(d:Device)<-[:LOGGED_IN_FROM]-(a2:Account)
            WHERE a1.`~id` < a2.`~id`
            WITH d, collect(DISTINCT a1.`~id`) + collect(DISTINCT a2.`~id`) AS cluster
            RETURN d.`~id` AS hub_device, size(cluster) AS cluster_size, cluster
            ORDER BY cluster_size DESC
            LIMIT 10
        """
        results = execute_query(neptune, query)

    for r in results[:10]:
        logger.info("  Community/Cluster: size=%s, sample=%s",
                     r.get("size") or r.get("cluster_size"),
                     r.get("sample_members") or r.get("cluster", [])[:5])

    return results


def run_pagerank(neptune: "boto3.client") -> list:
    """T2.4: Run PageRank to find high-influence nodes."""
    logger.info("\n=== T2.4: PageRank — High-Influence Nodes ===")

    query = """
        CALL neptune.algo.centrality.pageRank(
            {writeProperty: 'pagerank'}
        )
        YIELD node, score
        WITH node, score, labels(node) AS nodeType
        RETURN node.`~id` AS id, nodeType, score
        ORDER BY score DESC
        LIMIT 20
    """
    results = execute_query(neptune, query)

    if not results:
        logger.warning("PageRank not available, using degree centrality fallback...")
        # Focus on devices — they are the key fraud indicator nodes
        query = """
            MATCH (d:Device)<-[r:LOGGED_IN_FROM]-(a:Account)
            WITH d, count(DISTINCT a) AS degree
            RETURN d.`~id` AS id, ['Device'] AS nodeType, degree
            ORDER BY degree DESC
            LIMIT 20
        """
        results = execute_query(neptune, query)

    for r in results[:10]:
        logger.info("  %s (%s): score=%s",
                     r.get("id"), r.get("nodeType"),
                     r.get("score") or r.get("degree"))

    return results


def run_shortest_path(neptune: "boto3.client") -> list:
    """T2.5: Find shortest paths between known fraud entities."""
    logger.info("\n=== T2.5: Shortest Path Between Fraud Entities ===")

    # Test paths between accounts in different fraud rings
    test_pairs = [
        ("A0009", "A0027", "RING-1 members"),
        ("A0009", "A0073", "RING-1 members via shared device"),
        ("A0017", "A0036", "RING-4 members"),
        ("A0001", "A0043", "RING-3 members"),
    ]

    results = []
    for entity_a, entity_b, description in test_pairs:
        # Neptune Analytics doesn't support shortestPath() function.
        # Use variable-length match with increasing hop limits to find shortest.
        rows = []
        for hops in range(1, 5):
            query = f"""
                MATCH (a {{`~id`: '{entity_a}'}})-[*{hops}]-(b {{`~id`: '{entity_b}'}})
                RETURN {hops} AS path_length
                LIMIT 1
            """
            rows = execute_query(neptune, query)
            if rows:
                break
        if rows:
            path_len = rows[0]["path_length"]
            status = "PASS" if path_len <= 3 else "WARN"
            logger.info("  %s -> %s (%s): length=%d [%s]",
                         entity_a, entity_b, description, path_len, status)
            results.append({"entity_a": entity_a, "entity_b": entity_b,
                            "path_length": path_len, "description": description,
                            "status": status})
        else:
            logger.warning("  %s -> %s: NO PATH FOUND within 4 hops", entity_a, entity_b)
            results.append({"entity_a": entity_a, "entity_b": entity_b, "status": "FAIL"})

    return results


def run_shared_device_analysis(neptune: "boto3.client") -> list:
    """Bonus: Find all shared devices (key fraud indicator)."""
    logger.info("\n=== Shared Device Analysis ===")

    query = """
        MATCH (a1:Account)-[:LOGGED_IN_FROM]->(d:Device)<-[:LOGGED_IN_FROM]-(a2:Account)
        WHERE a1.`~id` < a2.`~id`
        WITH d.`~id` AS device_id, collect(DISTINCT a1.`~id`) + collect(DISTINCT a2.`~id`) AS accounts
        WITH device_id, accounts, size(accounts) AS num_accounts
        WHERE num_accounts > 2
        RETURN device_id, num_accounts, accounts
        ORDER BY num_accounts DESC
    """
    results = execute_query(neptune, query)

    for r in results:
        logger.info("  Device %s: %d accounts -> %s",
                     r["device_id"], r["num_accounts"], r["accounts"])

    return results


def main() -> None:
    session = boto3.Session(region_name=REGION)
    neptune = session.client("neptune-graph")

    # Check graph status first
    resp = neptune.get_graph(graphIdentifier=GRAPH_ID)
    status = resp["status"]
    logger.info("Graph %s status: %s", GRAPH_ID, status)

    if status != "AVAILABLE":
        logger.error("Graph is not AVAILABLE (status=%s). Wait for creation to complete.", status)
        return

    # Run all validations and algorithms
    node_results = validate_node_counts(neptune)
    edge_results = validate_edge_counts(neptune)
    communities = run_community_detection(neptune)
    pagerank = run_pagerank(neptune)
    paths = run_shortest_path(neptune)
    shared = run_shared_device_analysis(neptune)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("=== M2 VALIDATION SUMMARY ===")
    logger.info("=" * 60)

    node_pass = all(v["status"] == "PASS" for v in node_results.values())
    logger.info("T2.1 Node counts: %s", "PASS" if node_pass else "FAIL")

    edge_total = edge_results.get("total", {}).get("actual", 0)
    logger.info("T2.2 Edge count: %d (expected ~3347)", edge_total)

    logger.info("T2.3 Community detection: %d communities found", len(communities))
    logger.info("T2.4 PageRank: top node = %s",
                pagerank[0].get("id") if pagerank else "N/A")

    path_pass = all(p.get("status") == "PASS" for p in paths)
    logger.info("T2.5 Shortest path: %s", "PASS" if path_pass else "NEEDS_REVIEW")

    logger.info("T2.6 Graph Explorer: (manual check in AWS Console)")
    logger.info("  Shared devices found: %d", len(shared))


if __name__ == "__main__":
    main()
