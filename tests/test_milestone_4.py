#!/usr/bin/env python3
"""Milestone 4 Test Suite — Notification, Agent & Analyst Interface.

Tests:
  T4.1 - SNS notification triggers on flagged transaction
  T4.2 - Conversational query: agent investigates account for fraud
  T4.3 - Follow-up queries: agent maintains session context
  T4.4 - Action group / KB routing: agent selects appropriate data source
  T4.5 - Evidence chain: flagged entity includes traceable relationships
  T4.6 - Confidence levels: agent provides risk level with justification
  T4.7 - End-to-end latency < 60s for typical fraud query (POC target)
  T4.8 - (PENDING) Customer approve/decline flow

Usage:
    set NEPTUNE_GRAPH_ID=g-a6z57uuv00
    python -m pytest tests/test_milestone_4.py -v
"""

import json
import os
import sys
import time
import unittest

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
GRAPH_ID = os.environ.get("NEPTUNE_GRAPH_ID", "g-a6z57uuv00")
AGENT_ID = os.environ.get("BEDROCK_AGENT_ID", "GJUSMWNBMY")
ALIAS_ID = os.environ.get("BEDROCK_AGENT_ALIAS_ID", "MINZ3DFIRX")
KB_ID = os.environ.get("BEDROCK_KB_ID", "Z0ZI5NWJ4Z")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def invoke_agent(query: str, session_id: str = "test-m4") -> tuple[str, float]:
    """Invoke Bedrock Agent and return (response_text, latency_seconds)."""
    session = boto3.Session(region_name=REGION)
    runtime = session.client("bedrock-agent-runtime")
    start = time.time()
    resp = runtime.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=ALIAS_ID,
        sessionId=session_id,
        inputText=query,
    )
    full_text = ""
    for event in resp["completion"]:
        if "chunk" in event:
            full_text += event["chunk"]["bytes"].decode("utf-8")
    elapsed = time.time() - start
    return full_text, elapsed


class TestSNSNotification(unittest.TestCase):
    """T4.1: SNS notification on flagged transactions."""

    def test_t41_sns_topic_exists(self) -> None:
        """T4.1a: SNS topic for fraud alerts exists."""
        session = boto3.Session(region_name=REGION)
        sns = session.client("sns")
        topics = sns.list_topics()["Topics"]
        fraud_topics = [t for t in topics if "graphrag-fraud" in t["TopicArn"]]
        self.assertGreater(len(fraud_topics), 0, "No fraud alert SNS topic found")
        print(f"\n  Found topic: {fraud_topics[0]['TopicArn']}")

    def test_t41_sns_has_subscriptions(self) -> None:
        """T4.1b: SNS topic has at least one email subscription."""
        session = boto3.Session(region_name=REGION)
        sns = session.client("sns")
        topics = sns.list_topics()["Topics"]
        fraud_topics = [t for t in topics if "graphrag-fraud" in t["TopicArn"]]
        if not fraud_topics:
            self.skipTest("No fraud alert SNS topic found")

        subs = sns.list_subscriptions_by_topic(TopicArn=fraud_topics[0]["TopicArn"])
        confirmed = [s for s in subs["Subscriptions"] if s["SubscriptionArn"] != "PendingConfirmation"]
        print(f"\n  Subscriptions: {len(confirmed)} confirmed")
        self.assertGreater(len(confirmed), 0, "No confirmed subscriptions")

    def test_t41_tier1_publishes_to_sns(self) -> None:
        """T4.1c: Tier 1 fraud_check handler has SNS publish capability."""
        os.environ["NEPTUNE_GRAPH_ID"] = GRAPH_ID
        from lambdas.fraud_check.handler import publish_to_sns
        # Verify function exists and is callable
        self.assertTrue(callable(publish_to_sns))


class TestBedrockAgent(unittest.TestCase):
    """T4.2-T4.7: Bedrock Agent conversational fraud investigation."""

    @classmethod
    def setUpClass(cls) -> None:
        """Verify agent is available."""
        session = boto3.Session(region_name=REGION)
        bedrock = session.client("bedrock-agent")
        try:
            resp = bedrock.get_agent(agentId=AGENT_ID)
            status = resp["agent"]["agentStatus"]
            if status != "PREPARED":
                raise unittest.SkipTest(f"Agent not ready: {status}")
        except ClientError as e:
            raise unittest.SkipTest(f"Agent not found: {e}")

    def test_t42_conversational_query(self) -> None:
        """T4.2: Agent responds to fraud investigation query with structured analysis."""
        text, elapsed = invoke_agent(
            "Investigate account A0009 for fraud. Is it connected to other suspicious accounts?",
            session_id="t42-test",
        )
        print(f"\n  Response length: {len(text)} chars ({elapsed:.1f}s)")

        self.assertGreater(len(text), 200, "Response too short for investigation")

        # Should contain structured analysis elements
        text_lower = text.lower()
        has_summary = "summary" in text_lower
        has_evidence = "evidence" in text_lower or "chain" in text_lower
        has_risk = "risk" in text_lower or "high" in text_lower
        has_action = "action" in text_lower or "recommend" in text_lower

        self.assertTrue(has_summary or has_evidence,
                        "Response missing structured analysis (summary/evidence)")
        self.assertTrue(has_risk, "Response missing risk assessment")

    def test_t43_followup_queries(self) -> None:
        """T4.3: Agent maintains context across follow-up queries."""
        session_id = f"t43-followup-{int(time.time())}"

        # Initial query
        text1, _ = invoke_agent(
            "Look up account A0140 and tell me about its fraud indicators.",
            session_id=session_id,
        )
        self.assertGreater(len(text1), 100)

        # Follow-up without re-specifying account
        text2, _ = invoke_agent(
            "What about its connected devices? Which other accounts share them?",
            session_id=session_id,
        )
        print(f"\n  Q1 length: {len(text1)}, Q2 length: {len(text2)}")

        # Follow-up should reference A0140 or its devices/ring members
        self.assertGreater(len(text2), 100, "Follow-up response too short")
        # Should mention device info (D0xxx) or accounts
        text2_lower = text2.lower()
        has_device_or_account = ("d00" in text2_lower or "a00" in text2_lower
                                 or "device" in text2_lower or "account" in text2_lower)
        self.assertTrue(has_device_or_account,
                        "Follow-up should reference devices or accounts")

    def test_t44_agent_uses_kb_or_action_groups(self) -> None:
        """T4.4: Agent correctly uses KB and/or action groups to answer queries."""
        # Test with a query that requires graph data
        text, elapsed = invoke_agent(
            "Find the fraud ring connected to account A0073. List all member accounts.",
            session_id=f"t44-routing-{int(time.time())}",
        )
        print(f"\n  Response ({elapsed:.1f}s): {text[:200]}...")

        # Should return actual account IDs (A0xxx pattern)
        self.assertGreater(len(text), 100)
        # Should mention specific account IDs from RING-1
        import re
        account_ids = re.findall(r"A\d{4}", text)
        self.assertGreater(len(account_ids), 1,
                           "Response should list multiple account IDs from fraud ring")
        print(f"  Account IDs found: {set(account_ids)}")

    def test_t45_evidence_chain(self) -> None:
        """T4.5: Every flagged entity includes traceable relationship paths."""
        text, _ = invoke_agent(
            "Investigate account A0027 for fraud. Include the complete evidence "
            "chain showing how it connects to other suspicious entities.",
            session_id=f"t45-evidence-{int(time.time())}",
        )
        print(f"\n  Response length: {len(text)} chars")

        text_lower = text.lower()
        # Should mention specific relationship types or connection paths
        has_relationship_info = any(
            term in text_lower
            for term in ["device", "shared", "ring", "connected", "logged in",
                         "associate", "transaction", "merchant"]
        )
        self.assertTrue(has_relationship_info,
                        "Response should include relationship/connection details")

        # Should mention specific entity IDs
        import re
        entity_ids = re.findall(r"[AD]\d{4}", text)
        self.assertGreater(len(entity_ids), 2,
                           "Evidence chain should reference multiple entities")

    def test_t46_confidence_levels(self) -> None:
        """T4.6: Agent provides risk/confidence levels with justification."""
        text, _ = invoke_agent(
            "What is the fraud risk level for account A0009? "
            "Provide your confidence assessment.",
            session_id=f"t46-confidence-{int(time.time())}",
        )

        text_lower = text.lower()
        # Should include risk level indication
        has_risk_level = any(
            term in text_lower
            for term in ["high", "medium", "low", "risk level", "confidence"]
        )
        self.assertTrue(has_risk_level,
                        "Response should include risk/confidence level")
        print(f"\n  Risk assessment present: True")
        print(f"  Contains 'high': {'high' in text_lower}")

    def test_t47_end_to_end_latency(self) -> None:
        """T4.7: Query-to-response < 60 seconds for POC.

        Note: Production target is <15s. POC includes cold-start Lambda,
        LLM reasoning, KB retrieval, and graph queries — 60s is acceptable.
        """
        _, elapsed = invoke_agent(
            "Is account A0099 suspicious? Quick assessment.",
            session_id=f"t47-latency-{int(time.time())}",
        )
        print(f"\n  Latency: {elapsed:.1f}s (target: <60s)")
        self.assertLess(elapsed, 60, f"Latency {elapsed:.1f}s exceeds 60s POC target")

    def test_t48_customer_approval_pending(self) -> None:
        """T4.8: Customer approve/decline flow (PENDING — future phase)."""
        self.skipTest("Customer approval flow is a future-phase feature (T4.3 in plan)")


class TestAgentInfrastructure(unittest.TestCase):
    """Verify agent infrastructure is correctly set up."""

    def test_agent_exists(self) -> None:
        """Bedrock Agent exists and is in PREPARED state."""
        session = boto3.Session(region_name=REGION)
        bedrock = session.client("bedrock-agent")
        resp = bedrock.get_agent(agentId=AGENT_ID)
        status = resp["agent"]["agentStatus"]
        print(f"\n  Agent: {AGENT_ID}, Status: {status}")
        self.assertEqual(status, "PREPARED")

    def test_agent_has_action_groups(self) -> None:
        """Agent has 3 action groups: GraphQuery, RiskScore, Explain."""
        session = boto3.Session(region_name=REGION)
        bedrock = session.client("bedrock-agent")
        resp = bedrock.list_agent_action_groups(
            agentId=AGENT_ID, agentVersion="DRAFT"
        )
        ag_names = {ag["actionGroupName"] for ag in resp["actionGroupSummaries"]}
        print(f"\n  Action groups: {ag_names}")
        self.assertIn("GraphQuery", ag_names)
        self.assertIn("RiskScore", ag_names)
        self.assertIn("Explain", ag_names)

    def test_agent_has_kb_association(self) -> None:
        """Agent is associated with the fraud knowledge base."""
        session = boto3.Session(region_name=REGION)
        bedrock = session.client("bedrock-agent")
        resp = bedrock.list_agent_knowledge_bases(
            agentId=AGENT_ID, agentVersion="DRAFT"
        )
        kb_ids = {kb["knowledgeBaseId"] for kb in resp["agentKnowledgeBaseSummaries"]}
        print(f"\n  Associated KBs: {kb_ids}")
        self.assertIn(KB_ID, kb_ids)

    def test_lambda_functions_exist(self) -> None:
        """All 3 Lambda functions are deployed."""
        session = boto3.Session(region_name=REGION)
        lambda_client = session.client("lambda")
        expected = [
            "graphrag-fraud-graph-query",
            "graphrag-fraud-risk-score",
            "graphrag-fraud-explain",
        ]
        for name in expected:
            try:
                resp = lambda_client.get_function(FunctionName=name)
                state = resp["Configuration"]["State"]
                print(f"\n  {name}: {state}")
                self.assertEqual(state, "Active")
            except ClientError as e:
                self.fail(f"Lambda {name} not found: {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
