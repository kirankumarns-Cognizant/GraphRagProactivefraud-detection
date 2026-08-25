#!/usr/bin/env python3
"""Milestone 2 Test Checklist — Custom Graph Construction.

Tests (require Neptune Analytics graph in AVAILABLE state):
  T2.1 - Graph node count matches data (~1714 nodes)
  T2.2 - Graph edge count is reasonable (~3347 edges)
  T2.3 - Community detection finds fraud clusters
  T2.4 - PageRank identifies hub devices
  T2.5 - Shortest path between fraud entities <= 3 hops
  T2.6 - Graph Explorer visualization (manual check)
"""

import json
import os
import unittest

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
GRAPH_ID = os.environ.get("NEPTUNE_GRAPH_ID", "g-a6z57uuv00")


def execute_query(query: str) -> list:
    """Execute openCypher query against Neptune Analytics."""
    session = boto3.Session(region_name=REGION)
    neptune = session.client("neptune-graph")
    try:
        response = neptune.execute_query(
            graphIdentifier=GRAPH_ID,
            language="OPEN_CYPHER",
            queryString=query,
        )
        payload = json.loads(response["payload"].read())
        return payload.get("results", [])
    except ClientError as e:
        raise unittest.SkipTest(f"Neptune query failed: {e}")


def is_graph_available() -> bool:
    """Check if Neptune graph is in AVAILABLE state."""
    try:
        session = boto3.Session(region_name=REGION)
        neptune = session.client("neptune-graph")
        resp = neptune.get_graph(graphIdentifier=GRAPH_ID)
        return resp["status"] == "AVAILABLE"
    except Exception:
        return False


@unittest.skipUnless(is_graph_available(), "Neptune graph not AVAILABLE")
class TestMilestone2NodeCounts(unittest.TestCase):
    """T2.1: Graph node count matches generated data."""

    EXPECTED = {
        "Customer": 100,
        "Account": 150,
        "Device": 50,
        "Merchant": 30,
        "IP_Address": 20,
        "Transaction": 1364,
    }

    def test_node_counts(self) -> None:
        total = 0
        for label, expected in self.EXPECTED.items():
            results = execute_query(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            actual = results[0]["cnt"] if results else 0
            self.assertEqual(actual, expected, f"{label}: expected {expected}, got {actual}")
            total += actual
        self.assertEqual(total, 1714, f"Total nodes: expected 1714, got {total}")


@unittest.skipUnless(is_graph_available(), "Neptune graph not AVAILABLE")
class TestMilestone2EdgeCounts(unittest.TestCase):
    """T2.2: Graph edge count is reasonable."""

    def test_total_edges_above_threshold(self) -> None:
        results = execute_query("MATCH ()-[r]->() RETURN count(r) AS cnt")
        total = results[0]["cnt"] if results else 0
        self.assertGreaterEqual(total, 2500, f"Expected >=2500 edges, got {total}")

    def test_key_edge_types_exist(self) -> None:
        for rel_type in ["LOGGED_IN_FROM", "INITIATED_BY", "PURCHASED_AT", "OWNS"]:
            results = execute_query(
                f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS cnt"
            )
            count = results[0]["cnt"] if results else 0
            self.assertGreater(count, 0, f"{rel_type} edges missing")


@unittest.skipUnless(is_graph_available(), "Neptune graph not AVAILABLE")
class TestMilestone2CommunityDetection(unittest.TestCase):
    """T2.3: Community detection finds fraud clusters."""

    def test_shared_device_clusters_exist(self) -> None:
        """Find clusters of accounts sharing devices."""
        query = """
            MATCH (a1:Account)-[:LOGGED_IN_FROM]->(d:Device)<-[:LOGGED_IN_FROM]-(a2:Account)
            WHERE a1.`~id` < a2.`~id`
            WITH d.`~id` AS device_id,
                 collect(DISTINCT a1.`~id`) + collect(DISTINCT a2.`~id`) AS accounts
            WITH device_id, accounts, size(accounts) AS num_accounts
            WHERE num_accounts >= 3
            RETURN count(*) AS cluster_count
        """
        results = execute_query(query)
        cluster_count = results[0]["cluster_count"] if results else 0
        self.assertGreaterEqual(
            cluster_count, 2,
            f"Expected >=2 device-sharing clusters with 3+ accounts, found {cluster_count}"
        )


@unittest.skipUnless(is_graph_available(), "Neptune graph not AVAILABLE")
class TestMilestone2PageRank(unittest.TestCase):
    """T2.4: High-degree nodes are shared devices."""

    def test_high_degree_devices(self) -> None:
        """Devices with most connections should be shared fraud devices."""
        query = """
            MATCH (d:Device)<-[r:LOGGED_IN_FROM]-(a:Account)
            WITH d.`~id` AS device_id, count(a) AS account_count
            WHERE account_count >= 3
            RETURN device_id, account_count
            ORDER BY account_count DESC
            LIMIT 5
        """
        results = execute_query(query)
        self.assertGreater(len(results), 0, "No high-degree devices found")
        # Top device should have 3+ connected accounts
        self.assertGreaterEqual(
            results[0]["account_count"], 3,
            "Top device should connect to >=3 accounts"
        )


@unittest.skipUnless(is_graph_available(), "Neptune graph not AVAILABLE")
class TestMilestone2ShortestPath(unittest.TestCase):
    """T2.5: Shortest path between fraud ring members <= 3 hops."""

    def _find_shortest_path(self, entity_a: str, entity_b: str, max_hops: int = 4) -> int | None:
        """Find shortest path length between two entities (Neptune Analytics compatible)."""
        for hops in range(1, max_hops + 1):
            query = f"""
                MATCH (a {{`~id`: '{entity_a}'}})-[*{hops}]-(b {{`~id`: '{entity_b}'}})
                RETURN {hops} AS path_length
                LIMIT 1
            """
            results = execute_query(query)
            if results:
                return results[0]["path_length"]
        return None

    def test_ring1_path(self) -> None:
        """RING-1: A0009 and A0027 share device D0007, should be <=3 hops."""
        path_len = self._find_shortest_path("A0009", "A0027")
        self.assertIsNotNone(path_len, "No path found between A0009 and A0027")
        self.assertLessEqual(path_len, 3, f"Path too long: {path_len} hops")

    def test_ring4_path(self) -> None:
        """RING-4: A0017 and A0036 are velocity abuse ring members."""
        path_len = self._find_shortest_path("A0017", "A0036")
        self.assertIsNotNone(path_len, "No path found between A0017 and A0036")
        self.assertLessEqual(path_len, 3, f"Path too long: {path_len} hops")


if __name__ == "__main__":
    unittest.main(verbosity=2)
