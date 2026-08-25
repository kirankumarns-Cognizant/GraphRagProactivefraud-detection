"""MS-0 Test Gate — Project Setup & Health Check validation.

Tests:
  1. App launches without import errors
  2. Health check: Neptune graph reachable
  3. Health check: Neptune graph has data
  4. Health check: SNS topic resolves
  5. Health check: Bedrock accessible (or graceful amber)
  6. Persona accounts exist in Neptune
  7. Handler imports work outside Lambda context
"""

import os
import sys
import time
import unittest

# Ensure project root is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("NEPTUNE_GRAPH_ID", "g-a6z57uuv00")
os.environ.setdefault("AWS_REGION", "us-east-1")


class TestMS0Gate(unittest.TestCase):
    """MS-0 test gate — all must pass before proceeding to MS-1."""

    def test_01_app_imports(self):
        """App module imports without errors."""
        from streamlit_app.config.settings import PAGE_TITLE, PERSONAS, NEPTUNE_GRAPH_ID
        self.assertTrue(PAGE_TITLE)
        self.assertEqual(len(PERSONAS), 3)
        self.assertTrue(NEPTUNE_GRAPH_ID.startswith("g-"))
        print(f"\n  PASS: Config loaded — {PAGE_TITLE}")

    def test_02_handler_imports(self):
        """All handler functions import outside Lambda context."""
        from lambdas.fraud_check.handler import check_transaction
        from lambdas.explain.handler import gather_evidence, generate_explanation
        from lambdas.risk_score.handler import compute_network_risk

        self.assertTrue(callable(check_transaction))
        self.assertTrue(callable(gather_evidence))
        self.assertTrue(callable(generate_explanation))
        self.assertTrue(callable(compute_network_risk))
        print("\n  PASS: All 4 handler functions import successfully")

    def test_03_neptune_graph_reachable(self):
        """Neptune Analytics graph is available."""
        from streamlit_app.components.health_check import check_neptune
        status, detail = check_neptune()
        print(f"\n  Neptune: [{status}] {detail}")
        self.assertIn(status, ["green", "amber"],
                       f"Neptune not reachable: {detail}")

    def test_04_neptune_has_data(self):
        """Neptune graph contains nodes."""
        from streamlit_app.components.health_check import check_neptune_data
        status, detail = check_neptune_data()
        print(f"\n  Neptune data: [{status}] {detail}")
        self.assertEqual(status, "green",
                         f"Neptune graph has no data: {detail}")

    def test_05_sns_topic_exists(self):
        """SNS fraud alert topic exists."""
        from streamlit_app.components.health_check import check_sns
        status, detail = check_sns()
        print(f"\n  SNS: [{status}] {detail}")
        self.assertIn(status, ["green", "amber"],
                       f"SNS topic not found: {detail}")

    def test_06_bedrock_accessible(self):
        """Bedrock is accessible or gracefully reports unavailable."""
        from streamlit_app.components.health_check import check_bedrock
        status, detail = check_bedrock()
        print(f"\n  Bedrock: [{status}] {detail}")
        # Amber is acceptable (pending approval), only red is a failure
        self.assertIn(status, ["green", "amber"],
                       f"Bedrock critically unavailable: {detail}")

    def test_07_persona_accounts_exist(self):
        """All 3 persona accounts exist in Neptune with relationships."""
        from streamlit_app.components.warmup import warmup_all_personas
        results = warmup_all_personas()

        for key, result in results.items():
            print(f"\n  {result['persona_name']} ({result['account_id']}): "
                  f"{'EXISTS' if result['exists'] else 'MISSING'} — {result['detail']}")
            self.assertTrue(result["exists"],
                           f"Persona {key} ({result['account_id']}) not found in graph")
            if result["exists"]:
                self.assertGreater(result["total_connections"], 0,
                                  f"Persona {key} has no connections")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("MS-0 TEST GATE: Project Setup & Health Check")
    print("=" * 60)
    unittest.main(verbosity=2)
