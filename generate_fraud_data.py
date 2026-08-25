"""
GraphRAG Fraud Detection POC — Synthetic Data Generator
========================================================
Generates a realistic financial transaction dataset with embedded fraud patterns
for testing GraphRAG-based fraud detection on AWS (Neptune + Bedrock).

Output: CSV files (clean + labeled), Excel workbook, Neptune bulk-load CSVs,
        ground truth manifest, sample SAR documents, and openCypher queries.

Usage:
    pip install faker pandas openpyxl networkx
    python generate_fraud_data.py --output-dir ./data --seed 42

Reviewed: All critical issues (C1-C3), warnings (W1-W5), and suggestions (S1-S4) addressed.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import pandas as pd
from faker import Faker

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG = {
    "counts": {
        "customers": 100,
        "accounts": 150,
        "devices": 50,
        "merchants": 30,
        "ip_addresses": 20,
        "transactions_target": 1200,  # minimum target; reconciliation pass ensures this
    },
    "fraud_ratio": 0.20,  # [S4] configurable fraud-to-legitimate ratio
    "fraud_rings": {
        "count": 5,
        "min_members": 3,
        "max_members": 6,
    },
    "temporal": {
        "start_date": "2024-01-01",
        "end_date": "2024-06-30",
        "burst_accounts": 5,
        "burst_txn_count": 15,
        "off_hours_accounts": 4,
        "card_testing_accounts": 3,  # [W1] failed-then-success pattern
    },
    "geographic": {
        "impossible_travel_pairs": 3,
    },
    "account_types": ["savings", "checking", "credit_card"],
    "transaction_channels": ["online", "pos", "atm", "mobile", "wire"],
    "transaction_statuses": ["completed", "failed", "pending", "reversed"],
    "device_types": ["mobile", "desktop", "tablet"],
    "device_os": ["iOS 17", "Android 14", "Windows 11", "macOS 14", "Linux"],
    "merchant_categories": [
        "electronics", "grocery", "restaurant", "gas_station",
        "online_retail", "travel", "jewelry", "gaming",
        "cryptocurrency", "money_transfer",
    ],
    "regions": [
        {"name": "Sydney", "country": "AU", "lat": -33.87, "lon": 151.21},
        {"name": "Melbourne", "country": "AU", "lat": -37.81, "lon": 144.96},
        {"name": "Brisbane", "country": "AU", "lat": -27.47, "lon": 153.03},
        {"name": "Perth", "country": "AU", "lat": -31.95, "lon": 115.86},
        {"name": "London", "country": "UK", "lat": 51.51, "lon": -0.13},
        {"name": "New York", "country": "US", "lat": 40.71, "lon": -74.01},
        {"name": "Singapore", "country": "SG", "lat": 1.35, "lon": 103.82},
        {"name": "Lagos", "country": "NG", "lat": 6.52, "lon": 3.38},
    ],
    "risk_tiers": ["low", "medium", "high", "critical"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

fake = Faker(["en_AU", "en_US", "en_GB"])


def pick_region(rng: random.Random, domestic_only: bool = False) -> dict:
    pool = [r for r in CONFIG["regions"] if r["country"] == "AU"] if domestic_only else CONFIG["regions"]
    return rng.choice(pool)


def random_timestamp(rng: random.Random, start: datetime, end: datetime) -> datetime:
    delta = (end - start).total_seconds()
    return start + timedelta(seconds=rng.uniform(0, delta))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# ---------------------------------------------------------------------------
# Entity Generators
# ---------------------------------------------------------------------------

class FraudDataGenerator:
    """Generates all entities, relationships, and embedded fraud patterns."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        Faker.seed(seed)
        self.start_dt = datetime.fromisoformat(CONFIG["temporal"]["start_date"])
        self.end_dt = datetime.fromisoformat(CONFIG["temporal"]["end_date"])

        # [C1 FIX] Global counters for IDs — no more len()-based generation
        self._rel_counter = 0
        self._txn_counter = 0

        # Storage
        self.customers: List[dict] = []
        self.accounts: List[dict] = []
        self.devices: List[dict] = []
        self.merchants: List[dict] = []
        self.ip_addresses: List[dict] = []
        self.transactions: List[dict] = []
        self.relationships: List[dict] = []

        # Fraud tracking
        self.fraud_rings: List[dict] = []
        self.fraud_accounts: Set[str] = set()
        self.fraud_customers: Set[str] = set()
        self.ground_truth: List[dict] = []

    def _next_rel_id(self) -> str:
        self._rel_counter += 1
        return f"R{self._rel_counter:05d}"

    def _next_txn_id(self) -> str:
        self._txn_counter += 1
        return f"T{self._txn_counter:05d}"

    # -- Customers ----------------------------------------------------------

    def _generate_customers(self):
        for i in range(1, CONFIG["counts"]["customers"] + 1):
            region = pick_region(self.rng, domestic_only=(self.rng.random() < 0.7))
            self.customers.append({
                "customer_id": f"C{i:04d}",
                "first_name": fake.first_name(),
                "last_name": fake.last_name(),
                "email": fake.email(),
                "phone": fake.phone_number(),
                "date_of_birth": fake.date_of_birth(minimum_age=18, maximum_age=75).isoformat(),
                "region": region["name"],
                "country": region["country"],
                "risk_score": round(self.rng.uniform(0, 0.3), 3),
                "created_date": fake.date_between(
                    start_date=self.start_dt.date() - timedelta(days=1825),
                    end_date=self.start_dt.date() - timedelta(days=1),
                ).isoformat(),
                "is_fraud": False,
            })

    # -- Accounts -----------------------------------------------------------

    def _generate_accounts(self):
        customer_ids = [c["customer_id"] for c in self.customers]
        idx = 0
        for cid in customer_ids:
            idx += 1
            self.accounts.append(self._make_account(idx, cid))
        remaining = CONFIG["counts"]["accounts"] - idx
        for _ in range(remaining):
            idx += 1
            cid = self.rng.choice(customer_ids)
            self.accounts.append(self._make_account(idx, cid))

    def _make_account(self, idx: int, customer_id: str) -> dict:
        acct_type = self.rng.choice(CONFIG["account_types"])
        balance = round(self.rng.uniform(500, 150000), 2) if acct_type != "credit_card" else round(
            self.rng.uniform(-5000, 50000), 2
        )
        return {
            "account_id": f"A{idx:04d}",
            "customer_id": customer_id,
            "account_type": acct_type,
            "balance": balance,
            "currency": "AUD",
            "status": self.rng.choice(["active"] * 9 + ["suspended", "closed"]),
            "opened_date": fake.date_between(
                start_date=self.start_dt.date() - timedelta(days=1460),
                end_date=self.start_dt.date() - timedelta(days=1),
            ).isoformat(),
            "is_fraud": False,
        }

    # -- Devices ------------------------------------------------------------

    def _generate_devices(self):
        for i in range(1, CONFIG["counts"]["devices"] + 1):
            self.devices.append({
                "device_id": f"D{i:04d}",
                "device_type": self.rng.choice(CONFIG["device_types"]),
                "operating_system": self.rng.choice(CONFIG["device_os"]),
                "fingerprint": uuid.uuid4().hex[:16],
                "ip_address_id": f"IP{self.rng.randint(1, CONFIG['counts']['ip_addresses']):04d}",
                "first_seen": fake.date_between(
                    start_date=self.start_dt.date() - timedelta(days=730),
                    end_date=self.start_dt.date() - timedelta(days=1),
                ).isoformat(),
            })

    # -- Merchants ----------------------------------------------------------

    def _generate_merchants(self):
        for i in range(1, CONFIG["counts"]["merchants"] + 1):
            region = pick_region(self.rng)
            cat = self.rng.choice(CONFIG["merchant_categories"])
            risk = "high" if cat in ("cryptocurrency", "money_transfer", "gaming") else self.rng.choice(
                ["low"] * 6 + ["medium"] * 3 + ["high"]
            )
            self.merchants.append({
                "merchant_id": f"M{i:04d}",
                "merchant_name": fake.company(),
                "category": cat,
                "location": region["name"],
                "country": region["country"],
                "latitude": round(region["lat"] + self.rng.uniform(-0.5, 0.5), 4),
                "longitude": round(region["lon"] + self.rng.uniform(-0.5, 0.5), 4),
                "risk_tier": risk,
                "registration_date": fake.date_between(
                    start_date=self.start_dt.date() - timedelta(days=2190),
                    end_date=self.start_dt.date() - timedelta(days=180),
                ).isoformat(),
            })

    # -- IP Addresses -------------------------------------------------------

    def _generate_ip_addresses(self):
        for i in range(1, CONFIG["counts"]["ip_addresses"] + 1):
            region = pick_region(self.rng)
            is_vpn = self.rng.random() < 0.15
            self.ip_addresses.append({
                "ip_id": f"IP{i:04d}",
                "address": fake.ipv4_public(),
                "geo_location": region["name"],
                "country": region["country"],
                "is_vpn": is_vpn,
                "is_tor": is_vpn and self.rng.random() < 0.3,
                "isp": self.rng.choice(["Telstra", "Optus", "TPG", "Vodafone", "AWS", "Azure", "DigitalOcean"]),
            })

    # -- Fraud Rings --------------------------------------------------------

    def _embed_fraud_rings(self):
        available_customers = list(range(len(self.customers)))
        self.rng.shuffle(available_customers)

        ring_configs = [
            {"name": "Device Sharing Ring", "pattern": "shared_device",
             "description": "Multiple accounts accessed from the same physical devices across different customers."},
            {"name": "IP Rotation Ring", "pattern": "ip_rotation",
             "description": "Accounts using VPN/Tor IPs to mask geographic origin, rotating through shared infrastructure."},
            {"name": "Merchant Collusion Ring", "pattern": "merchant_collusion",
             "description": "Coordinated transactions to specific high-risk merchants with round-number amounts."},
            {"name": "Velocity Abuse Ring", "pattern": "velocity_abuse",
             "description": "Burst transactions across linked accounts within minutes of each other."},
            {"name": "Identity Layering Ring", "pattern": "identity_layering",
             "description": "Chain of accounts where money flows A to B to C to D to obscure the origin."},
        ]

        # [W4 FIX] Pre-select VPN IPs for IP rotation ring
        vpn_ips = [ip for ip in self.ip_addresses if ip["is_vpn"]]
        if not vpn_ips:
            # Force at least 2 IPs to be VPN
            for ip in self.ip_addresses[:2]:
                ip["is_vpn"] = True
                vpn_ips.append(ip)

        for ring_idx in range(CONFIG["fraud_rings"]["count"]):
            size = self.rng.randint(
                CONFIG["fraud_rings"]["min_members"],
                CONFIG["fraud_rings"]["max_members"],
            )
            if len(available_customers) < size:
                break

            member_indices = [available_customers.pop() for _ in range(size)]
            member_customer_ids = [self.customers[i]["customer_id"] for i in member_indices]
            ring_cfg = ring_configs[ring_idx]

            for idx in member_indices:
                self.customers[idx]["is_fraud"] = True
                self.customers[idx]["risk_score"] = round(self.rng.uniform(0.7, 1.0), 3)
                self.fraud_customers.add(self.customers[idx]["customer_id"])

            ring_accounts = [a for a in self.accounts if a["customer_id"] in member_customer_ids]
            for acct in ring_accounts:
                acct["is_fraud"] = True
                self.fraud_accounts.add(acct["account_id"])

            # Shared devices for this ring
            shared_device_ids = [
                f"D{self.rng.randint(1, CONFIG['counts']['devices']):04d}"
                for _ in range(self.rng.randint(1, 2))
            ]

            # [W4 FIX] For IP rotation ring, force shared VPN IPs on devices
            shared_ip_ids = []
            if ring_cfg["pattern"] == "ip_rotation" and vpn_ips:
                shared_vpn = self.rng.sample(vpn_ips, min(2, len(vpn_ips)))
                shared_ip_ids = [ip["ip_id"] for ip in shared_vpn]
                for did_str in shared_device_ids:
                    dev = next((d for d in self.devices if d["device_id"] == did_str), None)
                    if dev:
                        dev["ip_address_id"] = self.rng.choice(shared_ip_ids)

            # LOGGED_IN_FROM and SHARED_DEVICE edges
            for acct in ring_accounts:
                for did in shared_device_ids:
                    ts = random_timestamp(self.rng, self.start_dt, self.end_dt)
                    self.relationships.append({
                        "relationship_id": self._next_rel_id(),
                        "source_type": "account", "source_id": acct["account_id"],
                        "target_type": "device", "target_id": did,
                        "relationship_type": "LOGGED_IN_FROM",
                        "timestamp": ts.isoformat(),
                        "metadata": json.dumps({"ring_id": f"RING-{ring_idx + 1}"}),
                    })

                for other_acct in ring_accounts:
                    if acct["account_id"] < other_acct["account_id"]:
                        self.relationships.append({
                            "relationship_id": self._next_rel_id(),
                            "source_type": "account", "source_id": acct["account_id"],
                            "target_type": "account", "target_id": other_acct["account_id"],
                            "relationship_type": "SHARED_DEVICE",
                            "timestamp": random_timestamp(self.rng, self.start_dt, self.end_dt).isoformat(),
                            "metadata": json.dumps({"shared_devices": shared_device_ids}),
                        })

            # KNOWN_ASSOCIATE edges
            for i, cid1 in enumerate(member_customer_ids):
                for cid2 in member_customer_ids[i + 1:]:
                    self.relationships.append({
                        "relationship_id": self._next_rel_id(),
                        "source_type": "customer", "source_id": cid1,
                        "target_type": "customer", "target_id": cid2,
                        "relationship_type": "KNOWN_ASSOCIATE",
                        "timestamp": random_timestamp(self.rng, self.start_dt, self.end_dt).isoformat(),
                        "metadata": json.dumps({"ring_id": f"RING-{ring_idx + 1}"}),
                    })

            ring_record = {
                "ring_id": f"RING-{ring_idx + 1}",
                "ring_name": ring_cfg["name"],
                "pattern": ring_cfg["pattern"],
                "description": ring_cfg["description"],
                "member_count": size,
                "member_customer_ids": member_customer_ids,
                "member_account_ids": [a["account_id"] for a in ring_accounts],
                "shared_device_ids": shared_device_ids,
                "shared_ip_ids": shared_ip_ids,
            }
            self.fraud_rings.append(ring_record)
            self.ground_truth.append({"type": "fraud_ring", "id": ring_record["ring_id"], "details": ring_record})

    # -- Transactions -------------------------------------------------------

    def _add_transaction(self, acct_id: str, merch_id: str, amount: float,
                         ts: datetime, channel: str, status: str,
                         is_fraud: bool, fraud_pattern: Optional[str],
                         ring_id: Optional[str] = None) -> str:
        merch = next(m for m in self.merchants if m["merchant_id"] == merch_id)
        txn_id = self._next_txn_id()
        self.transactions.append({
            "transaction_id": txn_id,
            "account_id": acct_id,
            "merchant_id": merch_id,
            "amount": round(amount, 2),
            "currency": "AUD",
            "timestamp": ts.isoformat(),
            "channel": channel,
            "status": status,
            "location": merch["location"],
            "country": merch["country"],
            "is_fraud": is_fraud,
            "fraud_pattern": fraud_pattern,
        })
        meta = json.dumps({"ring_id": ring_id}) if ring_id else "{}"
        self.relationships.append({
            "relationship_id": self._next_rel_id(),
            "source_type": "transaction", "source_id": txn_id,
            "target_type": "account", "target_id": acct_id,
            "relationship_type": "INITIATED_BY",
            "timestamp": ts.isoformat(), "metadata": meta,
        })
        self.relationships.append({
            "relationship_id": self._next_rel_id(),
            "source_type": "transaction", "source_id": txn_id,
            "target_type": "merchant", "target_id": merch_id,
            "relationship_type": "PURCHASED_AT",
            "timestamp": ts.isoformat(), "metadata": meta,
        })
        return txn_id

    def _generate_transactions(self):
        account_ids = [a["account_id"] for a in self.accounts]
        merchant_ids = [m["merchant_id"] for m in self.merchants]

        # Legitimate transactions
        legit_count = int(CONFIG["counts"]["transactions_target"] * (1 - CONFIG["fraud_ratio"]))
        for _ in range(legit_count):
            self._add_transaction(
                acct_id=self.rng.choice(account_ids),
                merch_id=self.rng.choice(merchant_ids),
                amount=self.rng.lognormvariate(3.5, 1.2),
                ts=random_timestamp(self.rng, self.start_dt, self.end_dt),
                channel=self.rng.choice(CONFIG["transaction_channels"]),
                status=self.rng.choices(CONFIG["transaction_statuses"], weights=[85, 5, 5, 5])[0],
                is_fraud=False, fraud_pattern=None,
            )

        # Fraud ring transactions
        high_risk_merchants = [m["merchant_id"] for m in self.merchants if m["risk_tier"] == "high"] or merchant_ids[:3]

        for ring in self.fraud_rings:
            for acct_id in ring["member_account_ids"]:
                txn_count = self.rng.randint(5, 15)
                base_time = random_timestamp(self.rng, self.start_dt, self.end_dt)

                for j in range(txn_count):
                    merch_id = self.rng.choice(high_risk_merchants)
                    if ring["pattern"] == "velocity_abuse":
                        ts = base_time + timedelta(minutes=self.rng.randint(1, 30))
                        amount = self.rng.uniform(100, 2000)
                    elif ring["pattern"] == "merchant_collusion":
                        ts = random_timestamp(self.rng, self.start_dt, self.end_dt)
                        amount = self.rng.choice([500, 1000, 2000, 5000, 10000])
                    elif ring["pattern"] == "identity_layering":
                        ts = base_time + timedelta(hours=self.rng.randint(1, 48))
                        amount = self.rng.uniform(5000, 50000)
                    else:
                        ts = random_timestamp(self.rng, self.start_dt, self.end_dt)
                        amount = self.rng.uniform(200, 10000)

                    self._add_transaction(
                        acct_id=acct_id, merch_id=merch_id, amount=amount, ts=ts,
                        channel=self.rng.choice(["online", "mobile"]),
                        status=self.rng.choices(["completed", "failed", "completed", "reversed"], weights=[60, 15, 20, 5])[0],
                        is_fraud=True, fraud_pattern=ring["pattern"],
                        ring_id=ring["ring_id"],
                    )

    # -- Temporal Anomalies -------------------------------------------------

    def _embed_temporal_anomalies(self):
        non_fraud_accounts = [a for a in self.accounts if not a["is_fraud"]]
        merchant_ids = [m["merchant_id"] for m in self.merchants]

        # Burst transactions
        burst_accounts = self.rng.sample(
            non_fraud_accounts,
            min(CONFIG["temporal"]["burst_accounts"], len(non_fraud_accounts)),
        )
        for acct in burst_accounts:
            base_time = random_timestamp(self.rng, self.start_dt, self.end_dt)
            merch_id = self.rng.choice(merchant_ids)
            for _ in range(CONFIG["temporal"]["burst_txn_count"]):
                ts = base_time + timedelta(minutes=self.rng.randint(0, 59))
                self._add_transaction(
                    acct_id=acct["account_id"], merch_id=merch_id,
                    amount=self.rng.uniform(50, 500), ts=ts,
                    channel="online", status="completed",
                    is_fraud=True, fraud_pattern="velocity_burst",
                )
            self.ground_truth.append({
                "type": "temporal_anomaly", "subtype": "velocity_burst",
                "account_id": acct["account_id"],
                "description": f"{CONFIG['temporal']['burst_txn_count']} txns within 1 hour at {base_time.isoformat()}",
            })

        # Off-hours activity (2-5am)
        remaining = [a for a in non_fraud_accounts if a not in burst_accounts]
        off_hours_accounts = self.rng.sample(
            remaining, min(CONFIG["temporal"]["off_hours_accounts"], len(remaining)),
        )
        for acct in off_hours_accounts:
            for _ in range(self.rng.randint(3, 8)):
                day = random_timestamp(self.rng, self.start_dt, self.end_dt).date()
                ts = datetime.combine(day, datetime.min.time().replace(
                    hour=self.rng.randint(2, 4), minute=self.rng.randint(0, 59)
                ))
                self._add_transaction(
                    acct_id=acct["account_id"], merch_id=self.rng.choice(merchant_ids),
                    amount=self.rng.uniform(100, 3000), ts=ts,
                    channel=self.rng.choice(["online", "mobile"]), status="completed",
                    is_fraud=True, fraud_pattern="off_hours",
                )
            self.ground_truth.append({
                "type": "temporal_anomaly", "subtype": "off_hours_activity",
                "account_id": acct["account_id"],
                "description": "Multiple transactions between 2-5am local time",
            })

        # [W1 FIX] Card testing pattern: rapid failed then success
        card_test_remaining = [a for a in remaining if a not in off_hours_accounts]
        card_test_accounts = self.rng.sample(
            card_test_remaining,
            min(CONFIG["temporal"]["card_testing_accounts"], len(card_test_remaining)),
        )
        for acct in card_test_accounts:
            base_time = random_timestamp(self.rng, self.start_dt, self.end_dt)
            merch_id = self.rng.choice(merchant_ids)
            # 3-5 failed small-amount txns
            fail_count = self.rng.randint(3, 5)
            for k in range(fail_count):
                ts = base_time + timedelta(minutes=k * 2)
                self._add_transaction(
                    acct_id=acct["account_id"], merch_id=merch_id,
                    amount=self.rng.uniform(1, 10), ts=ts,
                    channel="online", status="failed",
                    is_fraud=True, fraud_pattern="card_testing",
                )
            # Followed by 1-2 successful large txns
            for k in range(self.rng.randint(1, 2)):
                ts = base_time + timedelta(minutes=fail_count * 2 + k * 5 + self.rng.randint(1, 10))
                self._add_transaction(
                    acct_id=acct["account_id"], merch_id=merch_id,
                    amount=self.rng.uniform(500, 5000), ts=ts,
                    channel="online", status="completed",
                    is_fraud=True, fraud_pattern="card_testing",
                )
            self.ground_truth.append({
                "type": "temporal_anomaly", "subtype": "card_testing",
                "account_id": acct["account_id"],
                "description": f"{fail_count} failed small txns followed by successful large txns within minutes at {base_time.isoformat()}",
            })

    # -- Geographic Anomalies -----------------------------------------------

    def _embed_geographic_anomalies(self):
        non_fraud_accounts = [a for a in self.accounts if not a["is_fraud"]]

        # [W5 FIX] Pre-verify distant region pairs have merchants
        distant_pairs = [
            (CONFIG["regions"][0], CONFIG["regions"][4]),  # Sydney ↔ London
            (CONFIG["regions"][1], CONFIG["regions"][5]),  # Melbourne ↔ New York
            (CONFIG["regions"][2], CONFIG["regions"][7]),  # Brisbane ↔ Lagos
        ]

        usable_pairs = []
        for r_a, r_b in distant_pairs:
            merchs_a = [m for m in self.merchants if m["location"] == r_a["name"]]
            merchs_b = [m for m in self.merchants if m["location"] == r_b["name"]]
            if merchs_a and merchs_b:
                usable_pairs.append((r_a, r_b, merchs_a, merchs_b))

        # If not enough natural pairs, create merchants in missing regions
        while len(usable_pairs) < CONFIG["geographic"]["impossible_travel_pairs"]:
            pair = distant_pairs[len(usable_pairs) % len(distant_pairs)]
            for region in pair:
                existing = [m for m in self.merchants if m["location"] == region["name"]]
                if not existing:
                    idx = len(self.merchants) + 1
                    self.merchants.append({
                        "merchant_id": f"M{idx:04d}",
                        "merchant_name": fake.company(),
                        "category": "electronics",
                        "location": region["name"],
                        "country": region["country"],
                        "latitude": round(region["lat"] + self.rng.uniform(-0.1, 0.1), 4),
                        "longitude": round(region["lon"] + self.rng.uniform(-0.1, 0.1), 4),
                        "risk_tier": "low",
                        "registration_date": fake.date_between(
                            start_date=self.start_dt.date() - timedelta(days=1095),
                            end_date=self.start_dt.date() - timedelta(days=180),
                        ).isoformat(),
                    })
            merchs_a = [m for m in self.merchants if m["location"] == pair[0]["name"]]
            merchs_b = [m for m in self.merchants if m["location"] == pair[1]["name"]]
            usable_pairs.append((pair[0], pair[1], merchs_a, merchs_b))

        travel_accounts = self.rng.sample(
            non_fraud_accounts,
            min(CONFIG["geographic"]["impossible_travel_pairs"], len(non_fraud_accounts)),
        )

        for i, acct in enumerate(travel_accounts):
            r_a, r_b, merchs_a, merchs_b = usable_pairs[i % len(usable_pairs)]
            day = random_timestamp(self.rng, self.start_dt, self.end_dt).date()

            ts1 = datetime.combine(day, datetime.min.time().replace(hour=9, minute=self.rng.randint(0, 59)))
            ts2 = datetime.combine(day, datetime.min.time().replace(hour=14, minute=self.rng.randint(0, 59)))

            self._add_transaction(
                acct_id=acct["account_id"], merch_id=self.rng.choice(merchs_a)["merchant_id"],
                amount=self.rng.uniform(50, 2000), ts=ts1,
                channel="pos", status="completed",
                is_fraud=True, fraud_pattern="impossible_travel",
            )
            self._add_transaction(
                acct_id=acct["account_id"], merch_id=self.rng.choice(merchs_b)["merchant_id"],
                amount=self.rng.uniform(50, 2000), ts=ts2,
                channel="pos", status="completed",
                is_fraud=True, fraud_pattern="impossible_travel",
            )

            dist_km = haversine_km(r_a["lat"], r_a["lon"], r_b["lat"], r_b["lon"])
            self.ground_truth.append({
                "type": "geographic_anomaly", "subtype": "impossible_travel",
                "account_id": acct["account_id"],
                "description": f"POS txn in {r_a['name']} at 09:XX and {r_b['name']} at 14:XX on {day.isoformat()} — {dist_km:.0f} km apart",
            })

    # -- Legitimate Relationships -------------------------------------------

    def _generate_legitimate_relationships(self):
        # OWNS: Customer → Account
        for acct in self.accounts:
            self.relationships.append({
                "relationship_id": self._next_rel_id(),
                "source_type": "customer", "source_id": acct["customer_id"],
                "target_type": "account", "target_id": acct["account_id"],
                "relationship_type": "OWNS",
                "timestamp": acct["opened_date"], "metadata": "{}",
            })

        # LOGGED_IN_FROM: Account → Device (non-fraud accounts)
        for acct in self.accounts:
            if acct["account_id"] in self.fraud_accounts:
                continue
            for _ in range(self.rng.randint(1, 3)):
                did = f"D{self.rng.randint(1, CONFIG['counts']['devices']):04d}"
                ts = random_timestamp(self.rng, self.start_dt, self.end_dt)
                self.relationships.append({
                    "relationship_id": self._next_rel_id(),
                    "source_type": "account", "source_id": acct["account_id"],
                    "target_type": "device", "target_id": did,
                    "relationship_type": "LOGGED_IN_FROM",
                    "timestamp": ts.isoformat(), "metadata": "{}",
                })

        # CONNECTED_VIA: Device → IP_Address
        for dev in self.devices:
            self.relationships.append({
                "relationship_id": self._next_rel_id(),
                "source_type": "device", "source_id": dev["device_id"],
                "target_type": "ip_address", "target_id": dev["ip_address_id"],
                "relationship_type": "CONNECTED_VIA",
                "timestamp": dev["first_seen"], "metadata": "{}",
            })

    # -- [W2 FIX] Transaction Reconciliation --------------------------------

    def _reconcile_transaction_count(self):
        """Ensure total transaction count meets the target minimum."""
        target = CONFIG["counts"]["transactions_target"]
        shortfall = target - len(self.transactions)
        if shortfall <= 0:
            return

        account_ids = [a["account_id"] for a in self.accounts if not a["is_fraud"]]
        merchant_ids = [m["merchant_id"] for m in self.merchants]

        for _ in range(shortfall):
            self._add_transaction(
                acct_id=self.rng.choice(account_ids),
                merch_id=self.rng.choice(merchant_ids),
                amount=self.rng.lognormvariate(3.5, 1.2),
                ts=random_timestamp(self.rng, self.start_dt, self.end_dt),
                channel=self.rng.choice(CONFIG["transaction_channels"]),
                status=self.rng.choices(CONFIG["transaction_statuses"], weights=[85, 5, 5, 5])[0],
                is_fraud=False, fraud_pattern=None,
            )

    # -- SAR Documents ------------------------------------------------------

    def _generate_sar_documents(self) -> List[str]:
        sars = []
        for ring in self.fraud_rings:
            members = ring["member_customer_ids"]
            member_names = [
                f"{c['first_name']} {c['last_name']}"
                for c in self.customers if c["customer_id"] in members
            ]
            accounts = ring["member_account_ids"]
            devices = ring["shared_device_ids"]

            fraud_txns = [t for t in self.transactions if t["account_id"] in accounts and t["is_fraud"]]
            total_amount = sum(t["amount"] for t in fraud_txns)

            sar = f"""SUSPICIOUS ACTIVITY REPORT (SAR)
{'='*60}
Report ID: SAR-{ring['ring_id']}
Date Filed: {datetime.now().strftime('%Y-%m-%d')}
Filing Institution: AnyCompany Bank (Australia)
Report Type: Coordinated Fraud Network

SUBJECT INFORMATION
-------------------
Ring Name: {ring['ring_name']}
Pattern Type: {ring['pattern']}
Number of Subjects: {ring['member_count']}

Subjects:
{chr(10).join(f'  - {name} ({cid})' for name, cid in zip(member_names, members))}

Accounts Involved:
{chr(10).join(f'  - {aid}' for aid in accounts)}

Shared Devices:
{chr(10).join(f'  - {did}' for did in devices)}

Shared IP Addresses:
{chr(10).join(f'  - {ipid}' for ipid in ring.get('shared_ip_ids', [])) or '  - None identified'}

NARRATIVE
---------
{ring['description']}

Between {CONFIG['temporal']['start_date']} and {CONFIG['temporal']['end_date']},
the above-named subjects conducted {len(fraud_txns)} suspicious transactions
totaling AUD {total_amount:,.2f} through accounts linked by shared devices
and network indicators.

The investigation revealed that these accounts are connected through:
1. Shared device fingerprints ({', '.join(devices)})
2. Overlapping IP addresses used for account access
3. Coordinated transaction timing patterns
4. Transactions directed to high-risk merchant categories

RECOMMENDED ACTIONS
-------------------
- Freeze accounts: {', '.join(accounts)}
- Enhanced monitoring on associated devices
- Escalate to law enforcement if threshold exceeded
- File additional SARs as investigation progresses

{'='*60}
END OF REPORT
"""
            sars.append(sar)
        return sars

    # -- Main Pipeline ------------------------------------------------------

    def generate(self) -> Dict[str, pd.DataFrame]:
        print("Generating customers...")
        self._generate_customers()
        print("Generating accounts...")
        self._generate_accounts()
        print("Generating devices...")
        self._generate_devices()
        print("Generating merchants...")
        self._generate_merchants()
        print("Generating IP addresses...")
        self._generate_ip_addresses()
        print("Embedding fraud rings...")
        self._embed_fraud_rings()
        print("Generating transactions...")
        self._generate_transactions()
        print("Embedding temporal anomalies...")
        self._embed_temporal_anomalies()
        print("Embedding geographic anomalies...")
        self._embed_geographic_anomalies()
        print("Generating legitimate relationships...")
        self._generate_legitimate_relationships()
        print("Reconciling transaction count...")
        self._reconcile_transaction_count()

        return {
            "customers": pd.DataFrame(self.customers),
            "accounts": pd.DataFrame(self.accounts),
            "devices": pd.DataFrame(self.devices),
            "merchants": pd.DataFrame(self.merchants),
            "ip_addresses": pd.DataFrame(self.ip_addresses),
            "transactions": pd.DataFrame(self.transactions),
            "relationships": pd.DataFrame(self.relationships),
        }

    def get_stats(self) -> dict:
        fraud_txns = [t for t in self.transactions if t["is_fraud"]]
        return {
            "total_customers": len(self.customers),
            "total_accounts": len(self.accounts),
            "total_devices": len(self.devices),
            "total_merchants": len(self.merchants),
            "total_ip_addresses": len(self.ip_addresses),
            "total_transactions": len(self.transactions),
            "total_relationships": len(self.relationships),
            "fraud_rings": len(self.fraud_rings),
            "fraud_customers": len(self.fraud_customers),
            "fraud_accounts": len(self.fraud_accounts),
            "fraud_transactions": len(fraud_txns),
            "fraud_transaction_pct": round(len(fraud_txns) / max(len(self.transactions), 1) * 100, 1),
            "total_fraud_amount": round(sum(t["amount"] for t in fraud_txns), 2),
            "temporal_anomalies": sum(1 for g in self.ground_truth if g["type"] == "temporal_anomaly"),
            "geographic_anomalies": sum(1 for g in self.ground_truth if g["type"] == "geographic_anomaly"),
            "fraud_patterns_embedded": list(set(
                t["fraud_pattern"] for t in self.transactions if t["fraud_pattern"]
            )),
        }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

LABEL_COLUMNS = {"is_fraud", "fraud_pattern"}


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in LABEL_COLUMNS if c in df.columns])


def export_data(gen: FraudDataGenerator, dataframes: Dict[str, pd.DataFrame], output_dir: str):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # [C3 FIX] Clean CSVs (no fraud labels) — for S3/Bedrock upload
    csv_clean_dir = out / "csv_clean"
    csv_clean_dir.mkdir(exist_ok=True)
    for name, df in dataframes.items():
        path = csv_clean_dir / f"{name}.csv"
        _clean_df(df).to_csv(path, index=False)
        print(f"  CSV (clean): {path} ({len(df)} rows)")

    # Labeled CSVs — for ground truth validation only
    csv_labeled_dir = out / "csv_labeled"
    csv_labeled_dir.mkdir(exist_ok=True)
    for name, df in dataframes.items():
        path = csv_labeled_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"  CSV (labeled): {path} ({len(df)} rows)")

    # Excel individual files (clean, for Bedrock KB)
    excel_dir = out / "excel_for_bedrock"
    excel_dir.mkdir(exist_ok=True)
    for name, df in dataframes.items():
        path = excel_dir / f"{name.capitalize()}.xlsx"
        _clean_df(df).to_excel(path, index=False)
        print(f"  Excel: {path}")

    # [S1] Neptune bulk-load CSV format
    neptune_dir = out / "neptune_bulk_load"
    neptune_dir.mkdir(exist_ok=True)
    _export_neptune_format(gen, dataframes, neptune_dir)

    # Ground truth
    gt_path = out / "ground_truth.json"
    with open(gt_path, "w") as f:
        json.dump({
            "fraud_rings": gen.fraud_rings,
            "ground_truth_events": gen.ground_truth,
            "statistics": gen.get_stats(),
        }, f, indent=2, default=str)
    print(f"  Ground truth: {gt_path}")

    # SAR documents
    sar_dir = out / "sar_documents"
    sar_dir.mkdir(exist_ok=True)
    sars = gen._generate_sar_documents()
    for i, sar in enumerate(sars):
        path = sar_dir / f"SAR_RING_{i + 1}.txt"
        with open(path, "w") as f:
            f.write(sar)
        print(f"  SAR: {path}")

    # [S2] Sample openCypher queries
    _export_sample_queries(out)

    # [S3] Data profile
    _export_data_profile(gen, dataframes, out)

    # Graph validation manifest
    _export_graph_validation(gen, out)


def _export_neptune_format(gen: FraudDataGenerator, dataframes: Dict[str, pd.DataFrame], neptune_dir: Path):
    """[S1] Export Neptune Analytics bulk-load CSVs with ~id, ~label, ~from, ~to headers."""
    # Nodes
    node_rows = []
    node_type_map = {
        "customers": ("customer_id", "Customer"),
        "accounts": ("account_id", "Account"),
        "devices": ("device_id", "Device"),
        "merchants": ("merchant_id", "Merchant"),
        "ip_addresses": ("ip_id", "IP_Address"),
        "transactions": ("transaction_id", "Transaction"),
    }
    for table_name, (id_col, label) in node_type_map.items():
        clean_df = _clean_df(dataframes[table_name])
        for _, row in clean_df.iterrows():
            node_row = {"~id": row[id_col], "~label": label}
            for col in clean_df.columns:
                if col != id_col:
                    node_row[col] = row[col]
            node_rows.append(node_row)

    nodes_df = pd.DataFrame(node_rows)
    nodes_path = neptune_dir / "nodes.csv"
    nodes_df.to_csv(nodes_path, index=False)
    print(f"  Neptune nodes: {nodes_path} ({len(nodes_df)} rows)")

    # Edges
    edge_rows = []
    for rel in gen.relationships:
        edge_rows.append({
            "~id": rel["relationship_id"],
            "~from": rel["source_id"],
            "~to": rel["target_id"],
            "~label": rel["relationship_type"],
            "timestamp": rel["timestamp"],
        })
    edges_df = pd.DataFrame(edge_rows)
    edges_path = neptune_dir / "edges.csv"
    edges_df.to_csv(edges_path, index=False)
    print(f"  Neptune edges: {edges_path} ({len(edges_df)} rows)")


def _export_sample_queries(out: Path):
    """[S2] Export sample openCypher queries for graph validation."""
    queries = """-- GraphRAG Fraud Detection POC — Sample openCypher Queries
-- Run these in Neptune Graph Explorer or via the Neptune API

-- 1. Count all node types
MATCH (n) RETURN labels(n) AS type, count(n) AS count ORDER BY count DESC

-- 2. Count all edge types
MATCH ()-[r]->() RETURN type(r) AS relationship, count(r) AS count ORDER BY count DESC

-- 3. Find accounts sharing devices (fraud ring indicator)
MATCH (a1:Account)-[:LOGGED_IN_FROM]->(d:Device)<-[:LOGGED_IN_FROM]-(a2:Account)
WHERE a1 <> a2
RETURN a1.account_id, a2.account_id, d.device_id

-- 4. Multi-hop: Find all entities within 3 hops of a specific account
MATCH path = (start:Account {account_id: 'A0001'})-[*1..3]-(connected)
RETURN path

-- 5. Find fraud rings via shared devices (community detection seed)
MATCH (a1:Account)-[:SHARED_DEVICE]-(a2:Account)
RETURN a1.account_id, a2.account_id

-- 6. Detect velocity bursts: accounts with >10 txns in 1 hour
MATCH (a:Account)<-[:INITIATED_BY]-(t:Transaction)
WITH a, t, datetime(t.timestamp) AS ts
WITH a, ts, count(t) AS txn_count
WHERE txn_count > 10
RETURN a.account_id, txn_count ORDER BY txn_count DESC

-- 7. Card testing pattern: failed then successful txns to same merchant
MATCH (a:Account)<-[:INITIATED_BY]-(t1:Transaction)-[:PURCHASED_AT]->(m:Merchant),
      (a)<-[:INITIATED_BY]-(t2:Transaction)-[:PURCHASED_AT]->(m)
WHERE t1.status = 'failed' AND t2.status = 'completed'
  AND datetime(t2.timestamp) > datetime(t1.timestamp)
RETURN a.account_id, m.merchant_id, t1.transaction_id, t2.transaction_id

-- 8. Impossible travel: same account, same day, distant locations
MATCH (a:Account)<-[:INITIATED_BY]-(t1:Transaction),
      (a)<-[:INITIATED_BY]-(t2:Transaction)
WHERE t1 <> t2
  AND t1.country <> t2.country
  AND date(datetime(t1.timestamp)) = date(datetime(t2.timestamp))
RETURN a.account_id, t1.location, t2.location, t1.timestamp, t2.timestamp

-- 9. Customer-to-merchant path (for explainability)
MATCH path = shortestPath(
  (c:Customer {customer_id: 'C0001'})-[*]-(m:Merchant {merchant_id: 'M0001'})
)
RETURN path

-- 10. High PageRank devices (most connected)
-- Note: Run PageRank algorithm first in Neptune Analytics, then query:
-- CALL neptune.algo.pageRank({}) YIELD node, score
-- RETURN node, score ORDER BY score DESC LIMIT 10
"""
    path = out / "sample_queries.cypher"
    with open(path, "w") as f:
        f.write(queries)
    print(f"  Sample queries: {path}")


def _export_data_profile(gen: FraudDataGenerator, dataframes: Dict[str, pd.DataFrame], out: Path):
    """[S3] Export data profiling summary."""
    txn_df = dataframes["transactions"]
    stats = gen.get_stats()

    profile = f"""# Data Profile — GraphRAG Fraud Detection POC

## Entity Counts
| Entity | Count |
|--------|-------|
| Customers | {stats['total_customers']} |
| Accounts | {stats['total_accounts']} |
| Devices | {stats['total_devices']} |
| Merchants | {stats['total_merchants']} |
| IP Addresses | {stats['total_ip_addresses']} |
| Transactions | {stats['total_transactions']} |
| Relationships | {stats['total_relationships']} |

## Fraud Summary
| Metric | Value |
|--------|-------|
| Fraud rings | {stats['fraud_rings']} |
| Fraud customers | {stats['fraud_customers']} |
| Fraud accounts | {stats['fraud_accounts']} |
| Fraud transactions | {stats['fraud_transactions']} ({stats['fraud_transaction_pct']}%) |
| Total fraud amount (AUD) | {stats['total_fraud_amount']:,.2f} |
| Temporal anomalies | {stats['temporal_anomalies']} |
| Geographic anomalies | {stats['geographic_anomalies']} |

## Fraud Patterns Embedded
{chr(10).join(f'- {p}' for p in stats['fraud_patterns_embedded'])}

## Transaction Amount Distribution
- Min: {txn_df['amount'].min():.2f}
- P25: {txn_df['amount'].quantile(0.25):.2f}
- Median: {txn_df['amount'].median():.2f}
- Mean: {txn_df['amount'].mean():.2f}
- P75: {txn_df['amount'].quantile(0.75):.2f}
- P95: {txn_df['amount'].quantile(0.95):.2f}
- Max: {txn_df['amount'].max():.2f}

## Transactions per Account
- Min: {txn_df.groupby('account_id').size().min()}
- Median: {txn_df.groupby('account_id').size().median():.0f}
- Max: {txn_df.groupby('account_id').size().max()}
- Accounts with 0 txns: {stats['total_accounts'] - txn_df['account_id'].nunique()}

## Fraud Ring Details
"""
    for ring in gen.fraud_rings:
        profile += f"""
### {ring['ring_id']}: {ring['ring_name']}
- Pattern: {ring['pattern']}
- Members: {ring['member_count']} customers, {len(ring['member_account_ids'])} accounts
- Shared devices: {', '.join(ring['shared_device_ids'])}
- Shared IPs: {', '.join(ring.get('shared_ip_ids', [])) or 'N/A'}
"""

    path = out / "data_profile.md"
    with open(path, "w") as f:
        f.write(profile)
    print(f"  Data profile: {path}")


def _export_graph_validation(gen: FraudDataGenerator, out: Path):
    node_counts = {
        "Customer": len(gen.customers),
        "Account": len(gen.accounts),
        "Device": len(gen.devices),
        "Merchant": len(gen.merchants),
        "IP_Address": len(gen.ip_addresses),
        "Transaction": len(gen.transactions),
    }
    edge_type_counts: Dict[str, int] = {}
    for r in gen.relationships:
        rtype = r["relationship_type"]
        edge_type_counts[rtype] = edge_type_counts.get(rtype, 0) + 1

    path = out / "graph_validation.json"
    with open(path, "w") as f:
        json.dump({
            "expected_node_counts": node_counts,
            "expected_total_nodes": sum(node_counts.values()),
            "expected_edge_type_counts": edge_type_counts,
            "expected_total_edges": sum(edge_type_counts.values()),
        }, f, indent=2)
    print(f"  Validation: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate synthetic fraud data for GraphRAG POC")
    parser.add_argument("--output-dir", default="./data", help="Output directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--fraud-ratio", type=float, default=None,
                        help="Fraud transaction ratio (0.0-1.0), overrides CONFIG")
    args = parser.parse_args()

    if args.fraud_ratio is not None:
        CONFIG["fraud_ratio"] = args.fraud_ratio

    print(f"\n{'='*60}")
    print("GraphRAG Fraud Detection — Synthetic Data Generator")
    print(f"{'='*60}\n")

    gen = FraudDataGenerator(seed=args.seed)
    dataframes = gen.generate()

    print(f"\n--- Exporting to {args.output_dir} ---\n")
    export_data(gen, dataframes, args.output_dir)

    stats = gen.get_stats()
    print(f"\n{'='*60}")
    print("GENERATION COMPLETE — Summary Statistics")
    print(f"{'='*60}")
    for key, val in stats.items():
        label = key.replace("_", " ").title()
        print(f"  {label:.<45} {val}")
    print(f"{'='*60}\n")

    # Graph connectivity validation
    print("Running graph connectivity validation...")
    G = nx.Graph()
    for r in gen.relationships:
        G.add_edge(
            f"{r['source_type']}:{r['source_id']}",
            f"{r['target_type']}:{r['target_id']}",
            type=r["relationship_type"],
        )
    components = list(nx.connected_components(G))
    largest = max(components, key=len)
    print(f"  Total graph nodes: {G.number_of_nodes()}")
    print(f"  Total graph edges: {G.number_of_edges()}")
    print(f"  Connected components: {len(components)}")
    print(f"  Largest component: {len(largest)} nodes ({len(largest)/G.number_of_nodes()*100:.1f}%)")
    print(f"  Density: {nx.density(G):.6f}")

    # Fraud ring connectivity verification
    print("\nFraud ring connectivity check:")
    for ring in gen.fraud_rings:
        ring_nodes = {f"account:{aid}" for aid in ring["member_account_ids"]}
        subgraph = G.subgraph([n for n in G.nodes if n in ring_nodes])
        n_nodes = subgraph.number_of_nodes()
        if n_nodes > 0:
            connected = nx.is_connected(subgraph) if n_nodes > 1 else True
            print(f"  {ring['ring_id']} ({ring['ring_name']}): "
                  f"{n_nodes} nodes, {subgraph.number_of_edges()} edges, connected={connected}")
        else:
            print(f"  {ring['ring_id']}: WARNING — ring accounts not directly connected (connected via devices)")

    # [C2] Verify transaction nodes are in the graph
    txn_nodes_in_graph = sum(1 for n in G.nodes if n.startswith("transaction:"))
    print(f"\n  Transaction nodes in graph: {txn_nodes_in_graph} "
          f"(expected: {len(gen.transactions)})")
    assert txn_nodes_in_graph == len(gen.transactions), \
        f"MISMATCH: {txn_nodes_in_graph} vs {len(gen.transactions)}"

    print(f"\nAll validations passed. Files written to: {Path(args.output_dir).resolve()}\n")


if __name__ == "__main__":
    main()