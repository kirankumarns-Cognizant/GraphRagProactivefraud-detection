# GraphRAG Fraud Detection POC

A proof-of-concept demonstrating how **Graph Retrieval-Augmented Generation (GraphRAG)** detects coordinated financial fraud through multi-hop relationship traversal, produces explainable outputs, and bridges probabilistic and deterministic AI.

Includes a **Streamlit demo UI** simulating bank customers making ecommerce transactions with real-time fraud scoring, AI-powered explainability, and customer notification workflows.

---

## Architecture

```
                        +------------------+
                        |   Streamlit UI   |
                        |  (Demo Frontend) |
                        +--------+---------+
                                 |
                    +------------+------------+
                    |                         |
            +-------v--------+     +---------v--------+
            |  Tier 1: Graph |     |  Tier 2: LLM     |
            |  Rules Engine  |     |  Explainability   |
            |  (< 5 seconds) |     |  (on-demand ~10s) |
            +-------+--------+     +---------+---------+
                    |                         |
            +-------v--------+     +---------v---------+
            | Neptune Analytics|    | Bedrock (Claude   |
            | (Graph DB)      |    |  Sonnet 4)        |
            +----------------+     +-------------------+
                                          |
                                   +------v------+
                                   | SNS Alerts  |
                                   | (Email)     |
                                   +-------------+
```

**Tier 1 (Deterministic):** 6 graph-based rules scored via Neptune Analytics openCypher queries. Sub-5-second decisions.

**Tier 2 (Probabilistic):** On-demand LLM-generated explanations using Claude Sonnet 4 via Amazon Bedrock. Evidence gathered from multi-hop graph traversal.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Cloud | AWS (us-east-1) |
| Graph DB | Amazon Neptune Analytics |
| LLM | Claude Sonnet 4 (via Bedrock) |
| Embeddings | Amazon Titan Text Embeddings V2 |
| Knowledge Base | Amazon Bedrock Knowledge Bases |
| Notifications | Amazon SNS |
| Storage | Amazon S3 |
| Frontend | Streamlit |
| Language | Python 3.8+ |
| Data Generation | Faker, Pandas, NetworkX |

---

## Prerequisites

1. **Python 3.8+** installed
2. **AWS CLI** configured with valid credentials (`aws configure` or environment variables)
3. **AWS Account** with access to:
   - Amazon Neptune Analytics
   - Amazon Bedrock (Claude Sonnet 4, Titan Embeddings V2)
   - Amazon SNS
   - Amazon S3
4. **Neptune Analytics graph** created and loaded with synthetic fraud data (graph ID: `g-a6z57uuv00`)
5. **SNS topic** `graphrag-fraud-alerts` with at least one email subscription confirmed

---

## Quick Start

### 1. Clone and Install Dependencies

```powershell
cd fraud-detection

# Install core dependencies
pip install -r requirements.txt

# Install Streamlit UI dependencies
pip install -r streamlit_app/requirements.txt
```

### 2. Set Environment Variables (Optional)

The application uses sensible defaults, but you can override them:

```powershell
# PowerShell
$env:NEPTUNE_GRAPH_ID = "g-a6z57uuv00"
$env:AWS_REGION = "us-east-1"
```

```bash
# Bash
export NEPTUNE_GRAPH_ID="g-a6z57uuv00"
export AWS_REGION="us-east-1"
```

### 3. Launch the Streamlit Demo

```powershell
python -m streamlit run streamlit_app/app.py
```

Open your browser to **http://localhost:8501**.

> **Note:** Use `python -m streamlit` instead of bare `streamlit` if the command is not on your PATH.

---

## Using the Demo

### Step 1: Health Check

Click **"Run Health Check"** in the sidebar to verify AWS service connectivity:
- Neptune Analytics (graph available)
- Neptune Data (nodes loaded)
- SNS Alerts (topic active)
- Bedrock LLM (model accessible)

### Step 2: Verify Personas

Click **"Verify Personas"** to confirm all three demo accounts exist in Neptune.

### Step 3: Run Scenarios

Select a persona and click **"Submit Transaction"**:

| Persona | Account | Expected Score | Expected Decision | Demo Narrative |
|---------|---------|---------------|-------------------|----------------|
| Sarah Chen (Genuine) | A0006 | 0-10 | APPROVE (green) | Normal customer, approved instantly |
| Viktor Petrov (Fraud) | A0009 | 80+ | REJECT (red) | Fraud ring member, blocked immediately |
| Maria Santos (Borderline) | A0020 | ~40 | REVIEW (amber) | Suspicious but uncertain, customer decides |

### Step 4: Explore Features

- **REJECT/REVIEW transactions:** Click **"Explain with AI"** for a Tier 2 LLM-generated analysis
- **REVIEW transactions:** Use **Approve/Reject** buttons to simulate customer decision
- **Notifications:** REVIEW transactions trigger SNS email alerts
- **Sidebar:** Track transaction history and system health

---

## Three-Tier Scoring Bands

| Band | Score Range | Decision | Action |
|------|-----------|----------|--------|
| APPROVE | 0 - 29 | Approved | Transaction proceeds |
| REVIEW | 30 - 59 | Pending Review | SNS notification sent, customer approve/reject |
| REJECT | 60 - 130 | Rejected | Transaction blocked |

### Tier 1 Rules (6 graph-based checks)

| Rule | Weight | Description |
|------|--------|-------------|
| Known Associate | 50 | Account within 2 hops of KNOWN_ASSOCIATE edge |
| Amount Anomaly | 25 | Transaction > 5x account average |
| Velocity Burst | 20 | Account has >10 recent transactions |
| High-Risk Merchant | 15 | High-risk merchant + amount > $500 |
| Shared Device | 10 | Device shared with 5+ other accounts |
| VPN/Tor IP | 10 | Connected to VPN/Tor IP via device |

---

## Running Tests

### Run All Tests (35 total)

```powershell
# MS-0: Project Setup & Health Check (7 tests)
python -m streamlit_app.tests.test_ms0_gate

# MS-1: Core Engine Wrappers (11 tests)
python -m streamlit_app.tests.test_ms1_gate

# MS-2/3/4: Personas, Dashboard, Notifications (10 tests)
python -m streamlit_app.tests.test_ms2_ms3_ms4_gate

# MS-5: Integration Tests (7 tests)
python -m streamlit_app.tests.test_ms5_integration
```

### Run All at Once

```powershell
python -m pytest streamlit_app/tests/ -v
```

### Run Original POC Milestone Tests

```powershell
# Milestone 0: Baseline GraphRAG KB
python -m pytest tests/test_milestone_0.py -v

# Milestone 2: Graph Build
python -m pytest tests/test_milestone_2.py -v

# Milestone 3: Tiered Pipeline
python -m pytest tests/test_milestone_3.py -v

# Milestone 4: Bedrock Agent + Notifications
python -m pytest tests/test_milestone_4.py -v

# Milestone 5: Demo & Docs
python -m pytest tests/test_milestone_5.py -v
```

### What Each Test Suite Validates

| Suite | Tests | What It Checks |
|-------|-------|---------------|
| `test_ms0_gate` | 7 | App imports, Neptune connectivity, SNS topic, Bedrock access, persona accounts exist |
| `test_ms1_gate` | 11 | Three-tier scoring (APPROVE/REVIEW/REJECT), boundary values, silent failure detection, circuit breaker, Tier 2 fallback, SNS routing |
| `test_ms2_ms3_ms4_gate` | 10 | Persona definitions, full scoring flows for all 3 personas, Tier 2 on-demand, SNS for REVIEW, approve/reject resolution |
| `test_ms5_integration` | 7 | End-to-end scenarios (genuine/fraud/borderline), error resilience (silent failure, Bedrock down, circuit breaker), performance (<5s per Tier 1) |

---

## Project Structure

```
fraud-detection/
|-- README.md                          # This file
|-- requirements.txt                   # Core Python dependencies
|
|-- streamlit_app/                     # Streamlit Demo UI
|   |-- app.py                         # Main entry point
|   |-- requirements.txt               # UI-specific dependencies
|   |-- config/
|   |   |-- settings.py                # Neptune ID, thresholds, personas
|   |-- engine/
|   |   |-- scoring.py                 # Three-tier scoring wrapper
|   |   |-- explainer.py               # Tier 2 LLM explanation wrapper
|   |   |-- notifier.py                # SNS notification wrapper
|   |-- components/
|   |   |-- health_check.py            # AWS service health indicators
|   |   |-- warmup.py                  # Persona account verification
|   |   |-- personas.py                # Persona selector cards
|   |   |-- transaction_form.py        # Transaction input + submission
|   |   |-- dashboard.py               # Risk gauge, rules, Tier 2 explain
|   |   |-- notifications.py           # Review panel, approve/reject
|   |-- tests/
|       |-- test_ms0_gate.py           # Setup & health check tests
|       |-- test_ms1_gate.py           # Engine wrapper tests
|       |-- test_ms2_ms3_ms4_gate.py   # UI component tests
|       |-- test_ms5_integration.py    # End-to-end integration tests
|
|-- data/                              # Generated synthetic data
|   |-- csv_clean/                     # Clean CSVs (no fraud labels)
|   |-- csv_labeled/                   # Labeled CSVs (evaluation only)
|   |-- neptune_bulk_load/             # Neptune bulk-load format
|   |-- ground_truth.json              # Fraud patterns ground truth
|
|-- lambdas/                           # Lambda handlers (imported by Streamlit)
|   |-- fraud_check/handler.py         # Tier 1: 6 graph-based rules
|   |-- explain/handler.py             # Tier 2: Evidence + LLM explanation
|   |-- risk_score/handler.py          # Network risk scoring
|
|-- scripts/                           # Deployment and utility scripts
|   |-- generate_fraud_data.py         # Synthetic data generator
|   |-- deploy_lambdas.py              # Lambda deployment
|   |-- create_bedrock_agent.py        # Bedrock Agent setup
|   |-- cleanup_resources.py           # Resource teardown (--dry-run supported)
|
|-- tests/                             # Original POC milestone tests
|-- infrastructure/                    # CloudFormation templates
```

---

## Error Handling & Safety

The application includes multiple safety mechanisms:

| Mechanism | Description |
|-----------|-------------|
| **Silent Failure Detection** | If Neptune returns score=0 in <100ms (likely a query error), the app defaults to REVIEW instead of false APPROVE |
| **Circuit Breaker** | After 3 consecutive Neptune failures, skips graph calls and returns REVIEW until manually reset |
| **Bedrock Fallback** | If LLM is unavailable, Tier 2 uses a template-based explanation instead of crashing |
| **Token Expiry Handling** | AWS credential errors are caught and displayed clearly, defaulting to REVIEW |
| **SNS Failure Isolation** | SNS publish failures are logged but never block the transaction flow |

**Safe default:** Any error condition results in **REVIEW** (never a false APPROVE).

---

## Configuration

All configuration is in `streamlit_app/config/settings.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `NEPTUNE_GRAPH_ID` | `g-a6z57uuv00` | Neptune Analytics graph identifier |
| `REGION` | `us-east-1` | AWS region |
| `SNS_TOPIC_NAME` | `graphrag-fraud-alerts` | SNS topic for notifications |
| `BAND_APPROVE_MAX` | `29` | Max score for APPROVE band |
| `BAND_REVIEW_MAX` | `59` | Max score for REVIEW band |
| `TIER2_TIMEOUT_SECONDS` | `30` | Timeout for Tier 2 LLM calls |
| `SONNET_MODEL_ID` | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Bedrock model for explanations |

---

## Cleanup

To tear down all AWS resources created by this POC:

```powershell
# Dry run (shows what would be deleted)
python scripts/cleanup_resources.py --dry-run

# Actual cleanup
python scripts/cleanup_resources.py

# Neptune only
python scripts/cleanup_resources.py --neptune-only
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `streamlit: not recognized` | Use `python -m streamlit run streamlit_app/app.py` |
| Health check shows red for Neptune | Verify graph `g-a6z57uuv00` is running: `aws neptune-graph get-graph --graph-identifier g-a6z57uuv00` |
| Health check shows red for SNS | Check topic exists: `aws sns list-topics` |
| Bedrock shows amber | Model access may be pending approval. Tier 2 will use template fallback. |
| Score=0 for all personas | Neptune graph may be empty. Re-run data load or check graph status. |
| SNS email not received | Confirm SNS subscription (check email for confirmation link) |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt && pip install -r streamlit_app/requirements.txt` |
| AWS credentials expired | Run `saml2aws login` or `aws sso login`, then restart the app |

---

## Key Metrics (from POC testing)

| Metric | Value |
|--------|-------|
| Tier 1 Latency | 0.7 - 4.3 seconds |
| Tier 2 Latency | 9.5 - 21.5 seconds |
| Genuine (A0006) Score | 10 / APPROVE |
| Fraud (A0009) Score | 90 / REJECT |
| Borderline (A0020) Score | 40 / REVIEW |
| Total Test Coverage | 35 tests, 100% pass |
| Graph Nodes | 1,714 |
| Fraud Rings Detected | 3-5 |

---

## How the Streamlit App Talks to Tier 1 and Tier 2

The Streamlit app **does not call Lambda functions remotely**. It **imports the handler functions directly as local Python modules** and calls them in-process. The only network calls are **boto3 to AWS services** (Neptune, Bedrock, SNS).

### Communication Flow

```
Streamlit App (app.py)
    |
    |-- engine/scoring.py          --imports-->  lambdas/fraud_check/handler.py
    |   calls score_transaction()                  |-- check_transaction()
    |                                              |     |-- Neptune openCypher queries (boto3)
    |
    |-- engine/explainer.py        --imports-->  lambdas/explain/handler.py
    |   calls explain_entity()                     |-- gather_evidence() --> Neptune
    |                                              |-- generate_explanation() --> Bedrock
    |
    |-- engine/notifier.py         --direct-->   SNS publish (boto3)
```
