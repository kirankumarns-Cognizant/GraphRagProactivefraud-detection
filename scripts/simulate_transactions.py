#!/usr/bin/env python3
"""Real-time transaction simulator for Tier 1 fraud detection demo.

Replays transactions from csv_labeled through the Tier 1 fraud check engine,
displays real-time APPROVE/FLAG decisions, and computes accuracy metrics
against ground truth.

Usage:
    python scripts/simulate_transactions.py --graph-id g-XXXXXXXXXX [--limit 50] [--delay 0.5]
"""

import argparse
import json
import os
import sys
import time

import pandas as pd

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lambdas.fraud_check.handler import check_transaction, publish_to_sns

# ANSI colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_ground_truth(data_dir: str) -> dict[str, bool]:
    """Load ground truth fraud labels from csv_labeled."""
    txns = pd.read_csv(os.path.join(data_dir, "csv_labeled", "transactions.csv"))
    if "is_fraud" in txns.columns:
        return dict(zip(txns["transaction_id"], txns["is_fraud"].astype(bool)))
    return {}


def load_transactions(data_dir: str, limit: int | None = None, shuffle: bool = True) -> pd.DataFrame:
    """Load transactions from csv_clean (no fraud labels — simulates real input)."""
    txns = pd.read_csv(os.path.join(data_dir, "csv_clean", "transactions.csv"))
    if shuffle:
        txns = txns.sample(frac=1, random_state=42).reset_index(drop=True)
    if limit:
        txns = txns.head(limit)
    return txns


def print_header() -> None:
    """Print simulator header."""
    print(f"\n{BOLD}{'='*80}{RESET}")
    print(f"{BOLD}  GraphRAG Fraud Detection — Tier 1 Real-Time Transaction Simulator{RESET}")
    print(f"{BOLD}{'='*80}{RESET}")
    print(f"  {'TXN ID':<14} {'ACCOUNT':<10} {'AMOUNT':>10} {'MERCHANT':<8} {'SCORE':>5} {'DECISION':<10} {'RULES':<25} {'LATENCY':>8}")
    print(f"  {'-'*14} {'-'*10} {'-'*10} {'-'*8} {'-'*5} {'-'*10} {'-'*25} {'-'*8}")


def print_result(result: dict, is_correct: bool | None = None) -> None:
    """Print a single transaction result with color coding."""
    decision = result["decision"]
    if decision == "FLAG":
        color = RED
        rules = ", ".join(r["rule"] for r in result["rules_triggered"])
    else:
        color = GREEN
        rules = "-"

    # Accuracy indicator
    accuracy_mark = ""
    if is_correct is True:
        accuracy_mark = " OK"
    elif is_correct is False:
        accuracy_mark = f" {YELLOW}MISS{RESET}"

    score = result.get('risk_score', 0)
    print(
        f"  {result['transaction_id']:<14} "
        f"{result['account_id']:<10} "
        f"${result['amount']:>9.2f} "
        f"{result['merchant_id']:<8} "
        f"{score:>5} "
        f"{color}{decision:<10}{RESET}"
        f"{rules:<25} "
        f"{result['latency_ms']:>6.0f}ms"
        f"{accuracy_mark}"
    )


def print_summary(
    total: int,
    flagged: int,
    approved: int,
    true_positives: int,
    false_positives: int,
    true_negatives: int,
    false_negatives: int,
    latencies: list[float],
) -> None:
    """Print accuracy and performance summary."""
    print(f"\n{BOLD}{'='*80}{RESET}")
    print(f"{BOLD}  SIMULATION SUMMARY{RESET}")
    print(f"{BOLD}{'='*80}{RESET}")

    print(f"\n  {BOLD}Decisions:{RESET}")
    print(f"    Total transactions:  {total}")
    print(f"    Approved:            {GREEN}{approved}{RESET}")
    print(f"    Flagged:             {RED}{flagged}{RESET}")

    if true_positives + false_positives + true_negatives + false_negatives > 0:
        precision = true_positives / max(true_positives + false_positives, 1)
        recall = true_positives / max(true_positives + false_negatives, 1)
        f1 = 2 * precision * recall / max(precision + recall, 0.001)

        print(f"\n  {BOLD}Accuracy (vs ground truth):{RESET}")
        print(f"    True Positives:    {true_positives:>5}  (fraud correctly flagged)")
        print(f"    False Positives:   {false_positives:>5}  (legitimate incorrectly flagged)")
        print(f"    True Negatives:    {true_negatives:>5}  (legitimate correctly approved)")
        print(f"    False Negatives:   {false_negatives:>5}  (fraud incorrectly approved)")
        print(f"    {BOLD}Precision:{RESET}          {precision:>5.1%}")
        print(f"    {BOLD}Recall:{RESET}             {recall:>5.1%}")
        print(f"    {BOLD}F1 Score:{RESET}           {f1:>5.1%}")

    if latencies:
        avg_lat = sum(latencies) / len(latencies)
        p50 = sorted(latencies)[len(latencies) // 2]
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        print(f"\n  {BOLD}Latency:{RESET}")
        print(f"    Average:           {avg_lat:>6.0f}ms")
        print(f"    P50:               {p50:>6.0f}ms")
        print(f"    P95:               {p95:>6.0f}ms")
        print(f"    Min:               {min(latencies):>6.0f}ms")
        print(f"    Max:               {max(latencies):>6.0f}ms")

    print(f"\n{'='*80}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate transactions through Tier 1 fraud detection")
    parser.add_argument("--graph-id", required=True, help="Neptune Analytics graph ID")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    parser.add_argument("--limit", type=int, default=50, help="Max transactions to process")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between transactions (seconds)")
    parser.add_argument("--no-delay", action="store_true", help="No delay (benchmark mode)")
    parser.add_argument("--no-shuffle", action="store_true", help="Don't shuffle transactions (process in order)")
    parser.add_argument("--sns-topic-arn", default="", help="SNS topic ARN for flagged alerts")
    args = parser.parse_args()

    # Set environment for the fraud check handler
    os.environ["NEPTUNE_GRAPH_ID"] = args.graph_id
    if args.sns_topic_arn:
        os.environ["SNS_TOPIC_ARN"] = args.sns_topic_arn

    # Load data
    ground_truth = load_ground_truth(args.data_dir)
    transactions = load_transactions(args.data_dir, args.limit, shuffle=not args.no_shuffle)

    print(f"\n  Loading {len(transactions)} transactions...")
    if ground_truth:
        print(f"  Ground truth available: {sum(ground_truth.values())} fraud / {len(ground_truth)} total")
    else:
        print(f"  {YELLOW}No ground truth — accuracy metrics unavailable{RESET}")

    print_header()

    # Counters
    flagged = 0
    approved = 0
    tp = fp = tn = fn = 0
    latencies = []

    for _, row in transactions.iterrows():
        result = check_transaction(
            account_id=row["account_id"],
            merchant_id=row["merchant_id"],
            amount=float(row["amount"]),
            transaction_id=row["transaction_id"],
        )

        latencies.append(result["latency_ms"])

        # Publish flagged transactions to SNS (if topic configured)
        if result["decision"] == "FLAG":
            publish_to_sns(result)

        # Check against ground truth
        is_fraud = ground_truth.get(row["transaction_id"])
        is_correct = None
        if is_fraud is not None:
            if result["decision"] == "FLAG":
                flagged += 1
                if is_fraud:
                    tp += 1
                    is_correct = True
                else:
                    fp += 1
                    is_correct = False
            else:
                approved += 1
                if is_fraud:
                    fn += 1
                    is_correct = False
                else:
                    tn += 1
                    is_correct = True
        else:
            if result["decision"] == "FLAG":
                flagged += 1
            else:
                approved += 1

        print_result(result, is_correct)

        if not args.no_delay:
            time.sleep(args.delay)

    # Summary
    total = flagged + approved
    print_summary(total, flagged, approved, tp, fp, tn, fn, latencies)


if __name__ == "__main__":
    main()
