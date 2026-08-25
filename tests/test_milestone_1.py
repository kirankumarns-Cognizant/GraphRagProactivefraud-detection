#!/usr/bin/env python3
"""Milestone 1 Test Checklist — Synthetic Data Validation.

Tests:
  T1.1 - Data volume matches spec (100 customers, 150 accounts, 1000+ txns)
  T1.2 - Fraud rings: 3-5 clusters of shared devices
  T1.3 - Temporal anomalies: burst patterns exist
  T1.4 - Geographic anomalies: impossible travel
  T1.5 - Ground truth document complete
  SEC  - No fraud labels in clean/Bedrock data
"""

import json
import os
import sys
import unittest

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


class TestMilestone1DataVolume(unittest.TestCase):
    """T1.1: Verify entity counts match specification."""

    def test_customer_count(self) -> None:
        df = pd.read_csv(os.path.join(DATA_DIR, "csv_labeled", "customers.csv"))
        self.assertEqual(len(df), 100, "Expected 100 customers")

    def test_account_count(self) -> None:
        df = pd.read_csv(os.path.join(DATA_DIR, "csv_labeled", "accounts.csv"))
        self.assertEqual(len(df), 150, "Expected 150 accounts")

    def test_device_count(self) -> None:
        df = pd.read_csv(os.path.join(DATA_DIR, "csv_labeled", "devices.csv"))
        self.assertEqual(len(df), 50, "Expected 50 devices")

    def test_merchant_count(self) -> None:
        df = pd.read_csv(os.path.join(DATA_DIR, "csv_labeled", "merchants.csv"))
        self.assertEqual(len(df), 30, "Expected 30 merchants")

    def test_transaction_count(self) -> None:
        df = pd.read_csv(os.path.join(DATA_DIR, "csv_labeled", "transactions.csv"))
        self.assertGreaterEqual(len(df), 1000, "Expected 1000+ transactions")


class TestMilestone1FraudRings(unittest.TestCase):
    """T1.2: Validate fraud ring clusters."""

    def setUp(self) -> None:
        with open(os.path.join(DATA_DIR, "ground_truth.json")) as f:
            self.gt = json.load(f)
        self.rings = self.gt["fraud_rings"]

    def test_ring_count(self) -> None:
        self.assertGreaterEqual(len(self.rings), 3, "Expected at least 3 fraud rings")
        self.assertLessEqual(len(self.rings), 5, "Expected at most 5 fraud rings")

    def test_ring_members(self) -> None:
        for ring in self.rings:
            accts = len(ring["member_account_ids"])
            self.assertGreaterEqual(
                accts, 3,
                f"{ring['ring_id']} has {accts} accounts (expected >=3)"
            )

    def test_ring_shared_devices(self) -> None:
        for ring in self.rings:
            devs = len(ring["shared_device_ids"])
            self.assertGreaterEqual(
                devs, 1,
                f"{ring['ring_id']} has {devs} shared devices (expected >=1)"
            )


class TestMilestone1TemporalAnomalies(unittest.TestCase):
    """T1.3: Verify temporal burst patterns."""

    def setUp(self) -> None:
        with open(os.path.join(DATA_DIR, "ground_truth.json")) as f:
            self.gt = json.load(f)
        self.temporal = [
            e for e in self.gt["ground_truth_events"]
            if e["type"] == "temporal_anomaly"
        ]

    def test_velocity_bursts(self) -> None:
        bursts = [e for e in self.temporal if e.get("subtype") == "velocity_burst"]
        self.assertGreaterEqual(
            len(bursts), 5,
            f"Expected >=5 velocity bursts, found {len(bursts)}"
        )

    def test_total_temporal_anomalies(self) -> None:
        self.assertGreaterEqual(
            len(self.temporal), 5,
            f"Expected >=5 temporal anomalies, found {len(self.temporal)}"
        )


class TestMilestone1GeographicAnomalies(unittest.TestCase):
    """T1.4: Verify impossible travel patterns."""

    def test_impossible_travel(self) -> None:
        with open(os.path.join(DATA_DIR, "ground_truth.json")) as f:
            gt = json.load(f)
        geo = [
            e for e in gt["ground_truth_events"]
            if e["type"] == "geographic_anomaly"
        ]
        self.assertGreaterEqual(
            len(geo), 3,
            f"Expected >=3 geographic anomalies, found {len(geo)}"
        )


class TestMilestone1GroundTruth(unittest.TestCase):
    """T1.5: Ground truth document completeness."""

    def test_ground_truth_exists(self) -> None:
        path = os.path.join(DATA_DIR, "ground_truth.json")
        self.assertTrue(os.path.exists(path), "ground_truth.json missing")

    def test_ground_truth_has_rings(self) -> None:
        with open(os.path.join(DATA_DIR, "ground_truth.json")) as f:
            gt = json.load(f)
        self.assertIn("fraud_rings", gt)
        self.assertGreater(len(gt["fraud_rings"]), 0)

    def test_ground_truth_has_events(self) -> None:
        with open(os.path.join(DATA_DIR, "ground_truth.json")) as f:
            gt = json.load(f)
        self.assertIn("ground_truth_events", gt)
        self.assertGreater(len(gt["ground_truth_events"]), 0)

    def test_ground_truth_has_statistics(self) -> None:
        with open(os.path.join(DATA_DIR, "ground_truth.json")) as f:
            gt = json.load(f)
        self.assertIn("statistics", gt)


class TestMilestone1Security(unittest.TestCase):
    """SEC: No fraud labels in clean/Bedrock data."""

    FORBIDDEN = {"is_fraud", "fraud_pattern", "fraud_ring", "fraud_type"}

    def _check_directory(self, dirname: str, reader) -> None:
        dirpath = os.path.join(DATA_DIR, dirname)
        for filename in os.listdir(dirpath):
            filepath = os.path.join(dirpath, filename)
            if not os.path.isfile(filepath):
                continue
            df = reader(filepath, nrows=0)
            found = set(c.lower() for c in df.columns) & self.FORBIDDEN
            self.assertEqual(
                len(found), 0,
                f"SECURITY: {dirname}/{filename} contains forbidden columns: {found}"
            )

    def test_csv_clean_no_fraud_labels(self) -> None:
        self._check_directory("csv_clean", pd.read_csv)

    def test_excel_for_bedrock_no_fraud_labels(self) -> None:
        self._check_directory("excel_for_bedrock", pd.read_excel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
