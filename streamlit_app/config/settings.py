"""Configuration settings for the Streamlit fraud detection demo.

All AWS resource identifiers and tunable thresholds are centralized here.
Values are read from environment variables with sensible defaults for the POC.
"""

import os

# ---------------------------------------------------------------------------
# AWS Region
# ---------------------------------------------------------------------------
REGION: str = os.environ.get("AWS_REGION", "us-east-1")

# ---------------------------------------------------------------------------
# Neptune Analytics — custom fraud graph (Tier 1 queries)
# ---------------------------------------------------------------------------
NEPTUNE_GRAPH_ID: str = os.environ.get("NEPTUNE_GRAPH_ID", "g-a6z57uuv00")

# Propagate to os.environ so that handler modules (which read os.environ at
# import time) pick up the correct values regardless of import order.
os.environ["NEPTUNE_GRAPH_ID"] = NEPTUNE_GRAPH_ID
os.environ["AWS_REGION"] = REGION

# ---------------------------------------------------------------------------
# SNS — fraud alert notifications
# ---------------------------------------------------------------------------
SNS_TOPIC_NAME: str = "graphrag-fraud-alerts"

# ---------------------------------------------------------------------------
# Bedrock — LLM for Tier 2 explanations
# ---------------------------------------------------------------------------
SONNET_MODEL_ID: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"

# ---------------------------------------------------------------------------
# Three-tier scoring bands
# ---------------------------------------------------------------------------
BAND_APPROVE_MAX: int = 29      # score 0-29  -> APPROVE
BAND_REVIEW_MAX: int = 59       # score 30-59 -> REVIEW
# score >= 60                   -> REJECT

# ---------------------------------------------------------------------------
# Persona defaults
# ---------------------------------------------------------------------------
PERSONAS: dict = {
    "genuine": {
        "name": "Sarah Chen",
        "account_id": "A0006",
        "description": "Regular shopper, consistent patterns, no fraud associations",
        "default_merchant": "M0015",
        "default_amount": 85.50,
        "default_description": "Weekly grocery order",
        "expected_band": "APPROVE",
        "avatar": "👩",
    },
    "fraud": {
        "name": "Viktor Petrov",
        "account_id": "A0009",
        "description": "RING-1 member, shared devices D0007/D0048, 8+ connected accounts",
        "default_merchant": "M0003",
        "default_amount": 2499.99,
        "default_description": "High-value electronics purchase",
        "expected_band": "REJECT",
        "avatar": "🕵️",
    },
    "borderline": {
        "name": "Maria Santos",
        "account_id": "A0020",
        "description": "Velocity anomaly, moderate risk signals, needs human review",
        "default_merchant": "M0008",
        "default_amount": 450.00,
        "default_description": "Online marketplace purchase",
        "expected_band": "REVIEW",
        "avatar": "👤",
    },
}

# ---------------------------------------------------------------------------
# UI settings
# ---------------------------------------------------------------------------
PAGE_TITLE: str = "GraphRAG Fraud Detection — Live Demo"
PAGE_ICON: str = "🛡️"
TIER2_TIMEOUT_SECONDS: int = 30
