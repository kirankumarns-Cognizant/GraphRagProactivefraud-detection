#!/usr/bin/env python3
"""Milestone 5 Test Suite — Documentation, Demo & Teardown.

Tests:
  T5.1 - Demo script runs end-to-end (all 5 scenarios have required components)
  T5.2 - Documentation complete (POC summary, demo script, findings)
  T5.3 - Cleanup script covers all resources

Usage:
    python -m pytest tests/test_milestone_5.py -v
"""

import json
import os
import sys
import unittest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, PROJECT_ROOT)


class TestDemoReadiness(unittest.TestCase):
    """T5.1: Demo script runs end-to-end — all components present."""

    def test_demo_script_exists(self) -> None:
        """Demo script file exists."""
        path = os.path.join(DOCS_DIR, "demo_script.md")
        self.assertTrue(os.path.isfile(path), "docs/demo_script.md not found")

    def test_demo_has_5_scenarios(self) -> None:
        """Demo script contains all 5 scenarios."""
        path = os.path.join(DOCS_DIR, "demo_script.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        scenarios = [
            "Scenario 1",
            "Scenario 2",
            "Scenario 3",
            "Scenario 4",
            "Scenario 5",
        ]
        for s in scenarios:
            self.assertIn(s, content, f"Missing {s} in demo script")

    def test_demo_covers_dual_audience(self) -> None:
        """Demo script addresses both business and technical audiences."""
        path = os.path.join(DOCS_DIR, "demo_script.md")
        with open(path, "r", encoding="utf-8") as f:
            content = content_lower = f.read().lower()

        self.assertIn("business", content_lower)
        self.assertIn("technical", content_lower)

    def test_simulator_script_exists(self) -> None:
        """Transaction simulator exists for Scenario 1."""
        path = os.path.join(SCRIPTS_DIR, "simulate_transactions.py")
        self.assertTrue(os.path.isfile(path))

    def test_tier1_handler_exists(self) -> None:
        """Tier 1 fraud check handler exists for Scenario 4."""
        path = os.path.join(PROJECT_ROOT, "lambdas", "fraud_check", "handler.py")
        self.assertTrue(os.path.isfile(path))

    def test_tier2_handler_exists(self) -> None:
        """Tier 2 explain handler exists for Scenario 4."""
        path = os.path.join(PROJECT_ROOT, "lambdas", "explain", "handler.py")
        self.assertTrue(os.path.isfile(path))

    def test_ground_truth_exists(self) -> None:
        """Ground truth data exists for validation."""
        path = os.path.join(DATA_DIR, "ground_truth.json")
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            gt = json.load(f)
        self.assertIn("fraud_rings", gt)
        self.assertGreaterEqual(len(gt["fraud_rings"]), 3)


class TestDocumentation(unittest.TestCase):
    """T5.2: Documentation complete — all required docs exist and have content."""

    def test_findings_has_executive_summary(self) -> None:
        """Findings doc has executive summary with key metrics."""
        path = os.path.join(DOCS_DIR, "findings.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Executive Summary", content)
        self.assertIn("87.2%", content, "Missing recall metric")
        self.assertIn("Tiered Architecture", content)

    def test_findings_has_all_milestones(self) -> None:
        """Findings doc covers all milestones M0-M4."""
        path = os.path.join(DOCS_DIR, "findings.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for m in ["Milestone 0", "Milestone 1", "Milestone 2", "Milestone 3", "Milestone 4"]:
            self.assertIn(m, content, f"Missing {m} in findings")

    def test_findings_has_production_roadmap(self) -> None:
        """Findings doc includes production roadmap."""
        path = os.path.join(DOCS_DIR, "findings.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Production Roadmap", content)
        self.assertIn("Phase 1", content)
        self.assertIn("Limitations", content)

    def test_demo_script_has_commands(self) -> None:
        """Demo script includes runnable commands."""
        path = os.path.join(DOCS_DIR, "demo_script.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("python scripts/simulate_transactions.py", content)
        self.assertIn("invoke_agent", content)

    def test_claude_md_exists(self) -> None:
        """CLAUDE.md project instructions exist."""
        path = os.path.join(PROJECT_ROOT, "CLAUDE.md")
        self.assertTrue(os.path.isfile(path))

    def test_plan_exists(self) -> None:
        """Master plan document exists."""
        path = os.path.join(PROJECT_ROOT, "graphrag-fraud-plan.md")
        self.assertTrue(os.path.isfile(path))


class TestCleanupReadiness(unittest.TestCase):
    """T5.3: Cleanup script covers all created resources."""

    def test_cleanup_script_exists(self) -> None:
        """Cleanup script exists."""
        path = os.path.join(SCRIPTS_DIR, "cleanup_resources.py")
        self.assertTrue(os.path.isfile(path))

    def test_cleanup_covers_all_resources(self) -> None:
        """Cleanup script references all resource types."""
        path = os.path.join(SCRIPTS_DIR, "cleanup_resources.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        resources = [
            "bedrock_agent",       # Bedrock Agent
            "knowledge_base",      # Bedrock KB
            "lambda",              # Lambda functions
            "neptune",             # Neptune graphs
            "sns",                 # SNS topic
            "s3",                  # S3 bucket
            "iam",                 # IAM roles
        ]
        for r in resources:
            self.assertIn(r, content.lower(), f"Cleanup missing {r} resource type")

    def test_cleanup_has_both_neptune_graphs(self) -> None:
        """Cleanup script includes both Neptune graph IDs."""
        path = os.path.join(SCRIPTS_DIR, "cleanup_resources.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("g-a6z57uuv00", content, "Missing custom graph ID")
        self.assertIn("g-e0cmuhfo37", content, "Missing KB graph ID")

    def test_cleanup_has_all_iam_roles(self) -> None:
        """Cleanup script includes all 4 IAM roles."""
        path = os.path.join(SCRIPTS_DIR, "cleanup_resources.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        roles = [
            "NeptuneAnalytics-S3-Read-graphrag-fraud-poc",
            "graphrag-fraud-poc-bedrock-kb-role",
            "graphrag-fraud-poc-bedrock-agent-role",
            "graphrag-fraud-poc-lambda-role",
        ]
        for role in roles:
            self.assertIn(role, content, f"Missing role: {role}")

    def test_cleanup_has_dry_run(self) -> None:
        """Cleanup script supports --dry-run flag."""
        path = os.path.join(SCRIPTS_DIR, "cleanup_resources.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("dry-run", content)
        self.assertIn("dry_run", content)

    def test_all_test_suites_exist(self) -> None:
        """Test files exist for all milestones."""
        tests_dir = os.path.join(PROJECT_ROOT, "tests")
        for m in range(6):
            path = os.path.join(tests_dir, f"test_milestone_{m}.py")
            self.assertTrue(os.path.isfile(path), f"Missing tests/test_milestone_{m}.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)
