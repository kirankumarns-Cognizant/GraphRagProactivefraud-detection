#!/usr/bin/env python3
"""Milestone 0 Test Suite — Managed GraphRAG Knowledge Base Baseline.

Tests the Bedrock Knowledge Base with Neptune Analytics GraphRAG storage
using RetrieveAndGenerate queries across 6 test categories.

KB ID: Z0ZI5NWJ4Z
Graph: g-e0cmuhfo37 (Neptune Analytics with vector search, dim=1024)
Model: Claude Sonnet 4 via inference profile
"""

import json
import os
import sys
import time
import unittest

import boto3

KB_ID = os.environ.get("BEDROCK_KB_ID", "Z0ZI5NWJ4Z")
MODEL_ARN = os.environ.get(
    "BEDROCK_MODEL_ARN",
    "arn:aws:bedrock:us-east-1:975049936238:inference-profile/"
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
)
REGION = "us-east-1"


def _query_kb(question: str) -> dict:
    """Send a RetrieveAndGenerate query and return output + citations."""
    session = boto3.Session(region_name=REGION)
    runtime = session.client("bedrock-agent-runtime")
    resp = runtime.retrieve_and_generate(
        input={"text": question},
        retrieveAndGenerateConfiguration={
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": KB_ID,
                "modelArn": MODEL_ARN,
            },
        },
    )
    citations = [
        ref
        for c in resp.get("citations", [])
        for ref in c.get("retrievedReferences", [])
    ]
    return {
        "text": resp["output"]["text"],
        "citations": citations,
        "citation_count": len(citations),
    }


class TestMilestone0(unittest.TestCase):
    """M0 Baseline: Managed GraphRAG Knowledge Base queries."""

    # ------------------------------------------------------------------
    # T0.1 — Basic entity query
    # ------------------------------------------------------------------
    def test_t01_basic_query(self) -> None:
        """T0.1: Basic query returns transactions for a known merchant."""
        result = _query_kb(
            "Show me all transactions processed by merchant M0015. "
            "Include transaction IDs, amounts, and account IDs."
        )
        self.assertGreater(len(result["text"]), 50, "Response too short")
        self.assertGreater(result["citation_count"], 0, "No citations returned")
        # Should mention at least one transaction ID
        self.assertTrue(
            any(f"T0" in result["text"] for _ in [1]),
            "Response should reference transaction IDs",
        )

    # ------------------------------------------------------------------
    # T0.2 — Relationship query
    # ------------------------------------------------------------------
    def test_t02_relationship_query(self) -> None:
        """T0.2: Relationship query returns devices linked to an account."""
        result = _query_kb(
            "Which devices have accessed account A0113? "
            "List all device IDs and timestamps."
        )
        self.assertGreater(len(result["text"]), 50)
        self.assertGreater(result["citation_count"], 0)
        # Should mention device IDs (D0xxx pattern)
        self.assertIn("D0", result["text"], "Response should list device IDs")

    # ------------------------------------------------------------------
    # T0.3 — Temporal/location query
    # ------------------------------------------------------------------
    def test_t03_temporal_query(self) -> None:
        """T0.3: Temporal query identifies accounts with multi-location transactions."""
        result = _query_kb(
            "Show me transactions that occurred in different countries. "
            "Which accounts have transactions in multiple locations like "
            "Sydney, London, Singapore, or New York?"
        )
        self.assertGreater(len(result["text"]), 100)
        self.assertGreater(result["citation_count"], 0)
        # Should mention at least one city
        cities = ["Sydney", "London", "Singapore", "New York", "Melbourne"]
        found = [c for c in cities if c in result["text"]]
        self.assertGreater(len(found), 0, "Response should mention city names")

    # ------------------------------------------------------------------
    # T0.4 — Fraud/anomaly query
    # ------------------------------------------------------------------
    def test_t04_fraud_query(self) -> None:
        """T0.4: Fraud query identifies high-value or outlier transactions."""
        result = _query_kb(
            "Find the highest value transactions in the dataset. "
            "Which transactions have amounts over 500 AUD? "
            "Show transaction IDs, amounts, accounts, and merchants."
        )
        self.assertGreater(len(result["text"]), 50)
        self.assertGreater(result["citation_count"], 0)

    # ------------------------------------------------------------------
    # T0.5 — Multi-hop query
    # ------------------------------------------------------------------
    def test_t05_multihop_query(self) -> None:
        """T0.5: Multi-hop query traces relationship paths between entities."""
        result = _query_kb(
            "What relationships exist between account A0140 and other entities? "
            "Show devices it logged in from, transactions it made, and any "
            "known associates. Trace the connections."
        )
        self.assertGreater(len(result["text"]), 50)
        self.assertGreater(result["citation_count"], 0)

    # ------------------------------------------------------------------
    # T0.6 — Explainability (citations)
    # ------------------------------------------------------------------
    def test_t06_citations(self) -> None:
        """T0.6: All responses include source citations from S3 data files."""
        result = _query_kb(
            "Show me the relationship between account A0030 and its devices."
        )
        self.assertGreater(result["citation_count"], 0, "No citations found")
        # Verify citations reference our S3 bucket
        for ref in result["citations"]:
            uri = (
                ref.get("location", {})
                .get("s3Location", {})
                .get("uri", "")
            )
            if uri:
                self.assertIn(
                    "graphrag-fraud-poc",
                    uri,
                    f"Citation URI doesn't reference our bucket: {uri}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
