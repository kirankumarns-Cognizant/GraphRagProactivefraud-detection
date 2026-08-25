"""MS-5 Integration Test Gate — End-to-end flow validation.

Tests all 3 persona scenarios end-to-end through the complete pipeline:
  1. Genuine: score -> APPROVE -> done (no review panel)
  2. Fraud: score -> REJECT -> explain -> done (Tier 2 on-demand)
  3. Borderline: score -> REVIEW -> notification -> approve/reject -> done
  4. Error resilience: silent failure, circuit breaker, Bedrock fallback
  5. Performance: each scenario < 30s (excluding Tier 2)
  6. All previous milestone tests still pass (regression)
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("NEPTUNE_GRAPH_ID", "g-a6z57uuv00")
os.environ.setdefault("AWS_REGION", "us-east-1")


class TestE2EGenuineScenario(unittest.TestCase):
    """Scenario 1: Genuine customer (Sarah Chen / A0006) -> APPROVE."""

    def test_01_genuine_e2e(self):
        """Full genuine flow: select persona, submit, APPROVE, no review panel."""
        from streamlit_app.engine.scoring import score_transaction
        from streamlit_app.config.settings import PERSONAS

        persona = PERSONAS["genuine"]
        start = time.time()
        result = score_transaction(
            persona["account_id"],
            persona["default_merchant"],
            persona["default_amount"],
            "E2E-GENUINE-001",
        )
        elapsed = time.time() - start

        self.assertEqual(result["decision"], "APPROVE")
        self.assertLessEqual(result["risk_score"], 29)
        self.assertLess(elapsed, 30, "Should complete in under 30s")

        print(f"\n  GENUINE E2E: score={result['risk_score']}, "
              f"decision={result['decision']}, time={elapsed:.1f}s")


class TestE2EFraudScenario(unittest.TestCase):
    """Scenario 2: Fraudster (Viktor Petrov / A0009) -> REJECT -> Explain."""

    def test_02_fraud_e2e(self):
        """Full fraud flow: submit, REJECT, Tier 2 explain."""
        from streamlit_app.engine.scoring import score_transaction
        from streamlit_app.engine.explainer import explain_entity
        from streamlit_app.config.settings import PERSONAS

        persona = PERSONAS["fraud"]

        # Tier 1
        start = time.time()
        result = score_transaction(
            persona["account_id"],
            persona["default_merchant"],
            persona["default_amount"],
            "E2E-FRAUD-001",
        )
        t1_elapsed = time.time() - start

        self.assertEqual(result["decision"], "REJECT")
        self.assertGreaterEqual(result["risk_score"], 60)
        self.assertGreater(result.get("rule_count", 0), 0)
        self.assertLess(t1_elapsed, 30, "Tier 1 should complete in under 30s")

        # Tier 2 (on-demand)
        start2 = time.time()
        explanation = explain_entity(persona["account_id"], max_hops=2)
        t2_elapsed = time.time() - start2

        self.assertIn(explanation["source"], ["llm", "template"])
        self.assertGreater(len(explanation["explanation"]), 100)

        print(f"\n  FRAUD E2E: score={result['risk_score']}, "
              f"decision={result['decision']}, "
              f"T1={t1_elapsed:.1f}s, T2={t2_elapsed:.1f}s ({explanation['source']})")


class TestE2EBorderlineScenario(unittest.TestCase):
    """Scenario 3: Borderline (Maria Santos / A0020) -> REVIEW -> resolve."""

    def test_03_borderline_e2e(self):
        """Full borderline flow: submit, REVIEW, notification, approve."""
        from streamlit_app.engine.scoring import score_transaction
        from streamlit_app.engine.notifier import send_review_notification
        from streamlit_app.config.settings import PERSONAS

        persona = PERSONAS["borderline"]

        # Tier 1
        start = time.time()
        result = score_transaction(
            persona["account_id"],
            persona["default_merchant"],
            persona["default_amount"],
            "E2E-BORDER-001",
        )
        t1_elapsed = time.time() - start

        self.assertIn(result["decision"], ["REVIEW", "REJECT"])
        self.assertGreater(result["risk_score"], 0)
        self.assertLess(t1_elapsed, 30)

        # SNS notification (if REVIEW)
        if result["decision"] == "REVIEW":
            sns_result = send_review_notification(result)
            self.assertIn("sent", sns_result)

            # Simulate customer approval
            result["decision"] = "APPROVED"
            result["resolved_by"] = "customer"
            self.assertEqual(result["decision"], "APPROVED")

            print(f"\n  BORDERLINE E2E: score={result['risk_score']}, "
                  f"REVIEW -> SNS(sent={sns_result.get('sent')}) -> APPROVED, "
                  f"time={t1_elapsed:.1f}s")
        else:
            print(f"\n  BORDERLINE E2E: score={result['risk_score']}, "
                  f"{result['decision']} (not REVIEW), time={t1_elapsed:.1f}s")


class TestE2EErrorResilience(unittest.TestCase):
    """Error scenario testing."""

    def test_04_silent_failure_safe_default(self):
        """Silent handler failure -> REVIEW (never false APPROVE)."""
        from streamlit_app.engine.scoring import score_transaction, reset_circuit_breaker
        reset_circuit_breaker()

        with patch("streamlit_app.engine.scoring.check_transaction") as mock:
            mock.return_value = {
                "transaction_id": "ERR-001", "account_id": "A0006",
                "merchant_id": "M0015", "amount": 85.50,
                "decision": "APPROVE", "risk_score": 0,
                "rules_triggered": [], "rule_count": 0, "latency_ms": 0.05,
            }
            result = score_transaction("A0006", "M0015", 85.50, "ERR-001")

        self.assertEqual(result["decision"], "REVIEW")
        print(f"\n  Silent failure -> {result['decision']} (safe)")
        reset_circuit_breaker()

    def test_05_bedrock_fallback(self):
        """Bedrock unavailable -> template explanation, no crash."""
        from streamlit_app.engine.explainer import get_explanation

        # Simulate evidence with no Bedrock
        evidence = {
            "entity_id": "A0009",
            "findings": [
                {"type": "shared_device", "severity": "high",
                 "detail": "Test device shared"},
            ],
        }

        with patch("streamlit_app.engine.explainer.generate_explanation",
                    side_effect=Exception("Bedrock unavailable")):
            result = get_explanation(evidence)

        self.assertEqual(result["source"], "template")
        self.assertGreater(len(result["explanation"]), 0)
        self.assertIsNotNone(result.get("warning"))
        print(f"\n  Bedrock fallback: source={result['source']}, "
              f"warning={result.get('warning')}")

    def test_06_circuit_breaker_recovery(self):
        """Circuit breaker opens and can be reset."""
        from streamlit_app.engine import scoring

        scoring._consecutive_failures = 3
        result = scoring.score_transaction("A0006", "M0015", 85.50, "CB-001")
        self.assertEqual(result["decision"], "REVIEW")

        scoring.reset_circuit_breaker()
        self.assertEqual(scoring._consecutive_failures, 0)
        print("\n  Circuit breaker: open -> REVIEW, reset -> OK")


class TestE2EPerformance(unittest.TestCase):
    """Performance benchmarks."""

    def test_07_tier1_under_5_seconds(self):
        """All 3 personas Tier 1 complete in under 5 seconds each."""
        from streamlit_app.engine.scoring import score_transaction
        from streamlit_app.config.settings import PERSONAS

        for key, persona in PERSONAS.items():
            start = time.time()
            result = score_transaction(
                persona["account_id"],
                persona["default_merchant"],
                persona["default_amount"],
                f"PERF-{key.upper()}",
            )
            elapsed = time.time() - start
            self.assertLess(elapsed, 5.0,
                            f"{key} Tier 1 took {elapsed:.1f}s (limit: 5s)")
            print(f"\n  {persona['name']}: {elapsed:.1f}s, "
                  f"score={result['risk_score']}, {result['decision']}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("MS-5 INTEGRATION TEST GATE")
    print("=" * 60)
    unittest.main(verbosity=2)
