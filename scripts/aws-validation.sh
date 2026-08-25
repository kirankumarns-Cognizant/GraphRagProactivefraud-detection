#!/usr/bin/env bash
# ============================================================
# GraphRAG Fraud Detection POC — AWS Environment Validator
# ============================================================
# Run this script to verify your AWS CLI, credentials,
# permissions, and Bedrock model access before starting.
#
# Usage:
#   chmod +x validate_aws.sh
#   ./validate_aws.sh
#
# Or directly:
#   bash validate_aws.sh
# ============================================================

set -euo pipefail

# --- Colors & formatting ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No color
BOLD='\033[1m'

PASS=0
FAIL=0
WARN=0

pass()  { ((PASS++)); echo -e "  ${GREEN}✔ PASS${NC}  $1"; }
fail()  { ((FAIL++)); echo -e "  ${RED}✘ FAIL${NC}  $1"; }
warn()  { ((WARN++)); echo -e "  ${YELLOW}⚠ WARN${NC}  $1"; }
info()  { echo -e "  ${BLUE}ℹ INFO${NC}  $1"; }
header(){ echo -e "\n${BOLD}── $1 ──${NC}"; }

echo ""
echo "============================================================"
echo "  GraphRAG Fraud Detection POC — AWS Environment Validator"
echo "============================================================"
echo ""

# =============================================================
# 1. AWS CLI Installation
# =============================================================
header "1. AWS CLI Installation"

if command -v aws &> /dev/null; then
    AWS_VERSION=$(aws --version 2>&1)
    pass "AWS CLI installed: ${AWS_VERSION}"
    
    # Check CLI version (v2 preferred)
    if echo "$AWS_VERSION" | grep -q "aws-cli/2"; then
        pass "AWS CLI v2 detected (recommended)"
    else
        warn "AWS CLI v1 detected — v2 is recommended. Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    fi
else
    fail "AWS CLI not installed"
    echo ""
    echo "  Install AWS CLI v2:"
    echo "    macOS:   brew install awscli"
    echo "    Linux:   curl 'https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip' -o 'awscliv2.zip' && unzip awscliv2.zip && sudo ./aws/install"
    echo "    Windows: https://awscli.amazonaws.com/AWSCLIV2.msi"
    echo ""
    echo "  After installing, run: aws configure"
    echo "  Then re-run this script."
    echo ""
    exit 1
fi

# =============================================================
# 2. AWS Credentials & Identity
# =============================================================
header "2. AWS Credentials & Identity"

# Check if credentials file or env vars exist
if [ -f "$HOME/.aws/credentials" ]; then
    pass "Credentials file found: ~/.aws/credentials"
elif [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
    pass "Credentials found in environment variables"
elif [ -n "${AWS_PROFILE:-}" ]; then
    info "Using AWS_PROFILE: ${AWS_PROFILE}"
else
    warn "No credentials file or environment variables detected"
fi

# Check config file
if [ -f "$HOME/.aws/config" ]; then
    pass "Config file found: ~/.aws/config"
    DEFAULT_REGION=$(aws configure get region 2>/dev/null || echo "not set")
    info "Default region: ${DEFAULT_REGION}"
else
    warn "No config file (~/.aws/config). Run: aws configure"
fi

# Verify identity with STS
echo ""
info "Verifying AWS identity (sts:GetCallerIdentity)..."
if STS_OUTPUT=$(aws sts get-caller-identity 2>&1); then
    pass "Successfully authenticated to AWS"
    
    ACCOUNT_ID=$(echo "$STS_OUTPUT" | grep -o '"Account": "[^"]*"' | cut -d'"' -f4)
    USER_ARN=$(echo "$STS_OUTPUT" | grep -o '"Arn": "[^"]*"' | cut -d'"' -f4)
    
    info "Account ID: ${ACCOUNT_ID}"
    info "Identity:   ${USER_ARN}"
    
    # Check if using root account (not recommended)
    if echo "$USER_ARN" | grep -q ":root"; then
        warn "You're using the ROOT account — use an IAM user or role instead"
    fi
else
    fail "Cannot authenticate to AWS"
    echo ""
    echo "  Error: ${STS_OUTPUT}"
    echo ""
    echo "  Troubleshooting:"
    echo "    1. Run: aws configure"
    echo "    2. Enter your Access Key ID and Secret Access Key"
    echo "    3. Set default region to: us-east-1"
    echo "    4. Re-run this script"
    echo ""
    exit 1
fi

# =============================================================
# 3. Region Check
# =============================================================
header "3. Region Configuration"

CURRENT_REGION=$(aws configure get region 2>/dev/null || echo "${AWS_DEFAULT_REGION:-not set}")

# GraphRAG (Bedrock KB + Neptune Analytics) supported regions
SUPPORTED_REGIONS=("us-east-1" "us-west-2" "eu-west-1" "ap-southeast-1")

if [[ " ${SUPPORTED_REGIONS[*]} " =~ " ${CURRENT_REGION} " ]]; then
    pass "Region '${CURRENT_REGION}' supports Bedrock KB GraphRAG + Neptune Analytics"
else
    warn "Region '${CURRENT_REGION}' may not support all required services"
    info "Recommended regions: ${SUPPORTED_REGIONS[*]}"
    info "To change: aws configure set region us-east-1"
fi

# =============================================================
# 4. Required Service Permissions
# =============================================================
header "4. Service Permissions Check"

# S3 — List buckets
if aws s3 ls &> /dev/null; then
    pass "Amazon S3: Can list buckets"
else
    fail "Amazon S3: Cannot list buckets (s3:ListAllMyBuckets denied)"
fi

# Bedrock — List foundation models
if aws bedrock list-foundation-models --max-results 1 &> /dev/null; then
    pass "Amazon Bedrock: Can list foundation models"
else
    fail "Amazon Bedrock: Access denied — verify Bedrock permissions in IAM"
fi

# Bedrock Agent Runtime — Check access
if aws bedrock-agent list-knowledge-bases --max-results 1 &> /dev/null 2>&1; then
    pass "Bedrock Knowledge Bases: Can list knowledge bases"
else
    warn "Bedrock Knowledge Bases: Cannot list (may need bedrock-agent permissions)"
fi

# Neptune Analytics — Check access
if aws neptune-graph list-graphs --max-results 1 &> /dev/null 2>&1; then
    pass "Neptune Analytics: Can list graphs"
else
    warn "Neptune Analytics: Cannot list graphs (may not have neptune-graph permissions or no graphs exist yet)"
fi

# IAM — Check ability to create roles (needed for KB setup)
if aws iam list-roles --max-items 1 &> /dev/null; then
    pass "IAM: Can list roles"
else
    warn "IAM: Cannot list roles — you may need admin help to create service roles"
fi

# =============================================================
# 5. Bedrock Model Access
# =============================================================
header "5. Bedrock Model Access"

info "Checking if required models are enabled..."

# Models needed for GraphRAG POC
REQUIRED_MODELS=(
    "us.anthropic.claude-haiku-4-5-20251001-v1:0:Graph construction"
    "us.anthropic.claude-sonnet-4-20250514-v1:0:Reasoning and query"
    "amazon.titan-embed-text-v2:0:Vector embeddings"
)

for model_entry in "${REQUIRED_MODELS[@]}"; do
    MODEL_ID="${model_entry%%:*}"
    MODEL_USE="${model_entry#*:}"
    
    if aws bedrock get-foundation-model --model-identifier "$MODEL_ID" &> /dev/null 2>&1; then
        pass "Model enabled: ${MODEL_ID} (${MODEL_USE})"
    else
        fail "Model NOT enabled: ${MODEL_ID} (${MODEL_USE})"
        info "Enable at: https://console.aws.amazon.com/bedrock/home#/modelaccess"
    fi
done

# =============================================================
# 6. Python Environment
# =============================================================
header "6. Python Environment (for data generator)"

if command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 --version 2>&1)
    pass "Python3 installed: ${PY_VERSION}"
    
    # Check version >= 3.8
    PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
    if [ "$PY_MINOR" -ge 8 ]; then
        pass "Python version >= 3.8 (compatible)"
    else
        warn "Python < 3.8 detected — upgrade recommended"
    fi
else
    fail "Python3 not installed"
fi

# Check required pip packages
if command -v pip3 &> /dev/null || command -v pip &> /dev/null; then
    PIP_CMD=$(command -v pip3 || command -v pip)
    pass "pip installed: $(${PIP_CMD} --version 2>&1 | head -1)"
    
    REQUIRED_PACKAGES=("faker" "pandas" "openpyxl" "networkx" "boto3")
    MISSING_PACKAGES=()
    
    for pkg in "${REQUIRED_PACKAGES[@]}"; do
        if python3 -c "import ${pkg}" &> /dev/null 2>&1; then
            pass "Package '${pkg}' installed"
        else
            MISSING_PACKAGES+=("$pkg")
            warn "Package '${pkg}' not installed"
        fi
    done
    
    if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
        echo ""
        info "Install missing packages:"
        echo "    pip3 install ${MISSING_PACKAGES[*]}"
    fi
else
    warn "pip not found — needed to install Python packages"
fi

# =============================================================
# 7. Quick S3 Write Test
# =============================================================
header "7. S3 Write Test (optional)"

TEST_BUCKET="graphrag-poc-test-${ACCOUNT_ID:-unknown}-$(date +%s)"
info "Attempting to create test bucket: ${TEST_BUCKET}"

if aws s3 mb "s3://${TEST_BUCKET}" &> /dev/null 2>&1; then
    pass "S3: Can create buckets"
    
    # Try writing a test file
    echo "GraphRAG POC test" > /tmp/graphrag_test.txt
    if aws s3 cp /tmp/graphrag_test.txt "s3://${TEST_BUCKET}/test.txt" &> /dev/null 2>&1; then
        pass "S3: Can upload files"
    else
        fail "S3: Cannot upload files (s3:PutObject denied)"
    fi
    
    # Cleanup
    aws s3 rb "s3://${TEST_BUCKET}" --force &> /dev/null 2>&1
    rm -f /tmp/graphrag_test.txt
    info "Test bucket cleaned up"
else
    warn "S3: Cannot create bucket (may need s3:CreateBucket permission, or bucket name conflict)"
fi

# =============================================================
# Summary
# =============================================================
echo ""
echo "============================================================"
echo "  VALIDATION SUMMARY"
echo "============================================================"
echo -e "  ${GREEN}Passed: ${PASS}${NC}"
echo -e "  ${RED}Failed: ${FAIL}${NC}"
echo -e "  ${YELLOW}Warnings: ${WARN}${NC}"
echo "============================================================"

if [ "$FAIL" -eq 0 ]; then
    echo ""
    echo -e "  ${GREEN}${BOLD}All critical checks passed!${NC}"
    echo "  You're ready to start Milestone 0."
    echo ""
    echo "  Next steps:"
    echo "    1. Run the synthetic data generator:"
    echo "       python3 generate_fraud_data.py --output-dir ./data"
    echo ""
    echo "    2. Upload to S3:"
    echo "       aws s3 mb s3://graphrag-fraud-poc-${ACCOUNT_ID}"
    echo "       aws s3 sync ./data/excel_for_bedrock/ s3://graphrag-fraud-poc-${ACCOUNT_ID}/data/"
    echo ""
    echo "    3. Create Bedrock Knowledge Base in the console:"
    echo "       https://console.aws.amazon.com/bedrock/home#/knowledge-bases"
    echo ""
elif [ "$FAIL" -le 2 ]; then
    echo ""
    echo -e "  ${YELLOW}${BOLD}Some issues found — fix the FAIL items above before proceeding.${NC}"
    echo ""
else
    echo ""
    echo -e "  ${RED}${BOLD}Multiple failures detected — review and fix before starting the POC.${NC}"
    echo ""
fi

echo "============================================================"
echo ""
