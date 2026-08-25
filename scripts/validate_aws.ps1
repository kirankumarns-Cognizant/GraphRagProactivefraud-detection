# ============================================================
# GraphRAG Fraud Detection POC - AWS Environment Validator
# ============================================================
# Save as: validate_aws.ps1 (UTF-8 without BOM)
#
# Run in PowerShell:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\validate_aws.ps1
# ============================================================

$ErrorActionPreference = "Continue"

$script:PassCount = 0
$script:FailCount = 0
$script:WarnCount = 0
$script:AccountId = "unknown"

function Write-Pass($msg) {
    $script:PassCount++
    Write-Host "  [PASS]  " -ForegroundColor Green -NoNewline
    Write-Host $msg
}

function Write-Fail($msg) {
    $script:FailCount++
    Write-Host "  [FAIL]  " -ForegroundColor Red -NoNewline
    Write-Host $msg
}

function Write-Warn($msg) {
    $script:WarnCount++
    Write-Host "  [WARN]  " -ForegroundColor Yellow -NoNewline
    Write-Host $msg
}

function Write-Info($msg) {
    Write-Host "  [INFO]  " -ForegroundColor Cyan -NoNewline
    Write-Host $msg
}

function Write-Header($msg) {
    Write-Host ""
    Write-Host "-- $msg --" -ForegroundColor White
}

Write-Host ""
Write-Host "============================================================"
Write-Host "  GraphRAG Fraud Detection POC - AWS Environment Validator"
Write-Host "============================================================"
Write-Host ""

# =============================================================
# 1. AWS CLI Installation
# =============================================================
Write-Header "1. AWS CLI Installation"

$awsCli = Get-Command aws -ErrorAction SilentlyContinue
if ($awsCli) {
    $awsVersionRaw = & aws --version 2>&1
    $awsVersionStr = "$awsVersionRaw"
    Write-Pass "AWS CLI installed: $awsVersionStr"

    if ($awsVersionStr -match "aws-cli/2") {
        Write-Pass "AWS CLI v2 detected (recommended)"
    }
    else {
        Write-Warn "AWS CLI v1 detected - v2 is recommended"
        Write-Info "Install v2: https://awscli.amazonaws.com/AWSCLIV2.msi"
    }
}
else {
    Write-Fail "AWS CLI not installed"
    Write-Host ""
    Write-Host "  Install AWS CLI v2 for Windows:"
    Write-Host "    Option 1: winget install Amazon.AWSCLI"
    Write-Host "    Option 2: Download https://awscli.amazonaws.com/AWSCLIV2.msi"
    Write-Host ""
    Write-Host "  After installing, restart PowerShell, run: aws configure"
    Write-Host "  Then re-run this script."
    Write-Host ""
    exit 1
}

# =============================================================
# 2. AWS Credentials and Identity
# =============================================================
Write-Header "2. AWS Credentials and Identity"

$credPath = Join-Path $env:USERPROFILE ".aws\credentials"
$configPath = Join-Path $env:USERPROFILE ".aws\config"

if (Test-Path $credPath) {
    Write-Pass "Credentials file found: $credPath"
}
elseif ($env:AWS_ACCESS_KEY_ID) {
    Write-Pass "Credentials found in environment variable AWS_ACCESS_KEY_ID"
}
elseif ($env:AWS_PROFILE) {
    Write-Info "Using AWS_PROFILE: $($env:AWS_PROFILE)"
}
else {
    Write-Warn "No credentials file or environment variables detected"
    Write-Info "Run: aws configure"
}

if (Test-Path $configPath) {
    Write-Pass "Config file found: $configPath"
    $defaultRegion = & aws configure get region 2>&1
    if ($LASTEXITCODE -eq 0 -and $defaultRegion) {
        Write-Info "Default region: $defaultRegion"
    }
    else {
        Write-Warn "No default region set. Run: aws configure set region us-east-1"
    }
}
else {
    Write-Warn "No config file found. Run: aws configure"
}

# Verify identity
Write-Host ""
Write-Info "Verifying AWS identity (sts:GetCallerIdentity)..."

$stsRaw = & aws sts get-caller-identity 2>&1
if ($LASTEXITCODE -eq 0) {
    try {
        $stsJson = $stsRaw | ConvertFrom-Json
        Write-Pass "Successfully authenticated to AWS"
        Write-Info "Account ID: $($stsJson.Account)"
        Write-Info "Identity:   $($stsJson.Arn)"
        $script:AccountId = $stsJson.Account

        if ($stsJson.Arn -match ":root") {
            Write-Warn "Using ROOT account - use an IAM user or role instead"
        }
    }
    catch {
        Write-Pass "Authenticated (could not parse details)"
    }
}
else {
    Write-Fail "Cannot authenticate to AWS"
    Write-Host ""
    Write-Host "  Troubleshooting:"
    Write-Host "    1. Run: aws configure"
    Write-Host "    2. Enter your Access Key ID and Secret Access Key"
    Write-Host "    3. Set default region to: us-east-1"
    Write-Host "    4. Re-run this script"
    Write-Host ""
    exit 1
}

# =============================================================
# 3. Region Check
# =============================================================
Write-Header "3. Region Configuration"

$currentRegion = & aws configure get region 2>&1
if ($LASTEXITCODE -ne 0 -or -not $currentRegion) {
    $currentRegion = $env:AWS_DEFAULT_REGION
}
if (-not $currentRegion) {
    $currentRegion = "not set"
}

$supportedRegions = @("us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1")

if ($supportedRegions -contains $currentRegion) {
    Write-Pass "Region '$currentRegion' supports Bedrock KB GraphRAG + Neptune Analytics"
}
else {
    Write-Warn "Region '$currentRegion' may not support all required services"
    Write-Info ("Recommended regions: " + ($supportedRegions -join ", "))
    Write-Info "To change: aws configure set region us-east-1"
}

# =============================================================
# 4. Required Service Permissions
# =============================================================
Write-Header "4. Service Permissions Check"

# S3
$null = & aws s3 ls 2>&1
if ($LASTEXITCODE -eq 0) { Write-Pass "Amazon S3: Can list buckets" }
else { Write-Fail "Amazon S3: Cannot list buckets" }

# Bedrock
$null = & aws bedrock list-foundation-models --max-results 1 2>&1
if ($LASTEXITCODE -eq 0) { Write-Pass "Amazon Bedrock: Can list foundation models" }
else { Write-Fail "Amazon Bedrock: Access denied - check Bedrock permissions in IAM" }

# Bedrock Knowledge Bases
$null = & aws bedrock-agent list-knowledge-bases --max-results 1 2>&1
if ($LASTEXITCODE -eq 0) { Write-Pass "Bedrock Knowledge Bases: Can list knowledge bases" }
else { Write-Warn "Bedrock Knowledge Bases: Cannot list (may need bedrock-agent permissions)" }

# Neptune Analytics
$null = & aws neptune-graph list-graphs --max-results 1 2>&1
if ($LASTEXITCODE -eq 0) { Write-Pass "Neptune Analytics: Can list graphs" }
else { Write-Warn "Neptune Analytics: Cannot list graphs (ok if no graphs exist yet)" }

# IAM
$null = & aws iam list-roles --max-items 1 2>&1
if ($LASTEXITCODE -eq 0) { Write-Pass "IAM: Can list roles" }
else { Write-Warn "IAM: Cannot list roles - may need admin help for service roles" }

# =============================================================
# 5. Bedrock Model Access
# =============================================================
Write-Header "5. Bedrock Model Access"

Write-Info "Checking if required models are enabled..."

$models = @(
    @{ Id = "us.anthropic.claude-haiku-4-5-20251001-v1:0";   Use = "Graph construction" },
    @{ Id = "us.anthropic.claude-sonnet-4-20250514-v1:0"; Use = "Reasoning and query" },
    @{ Id = "amazon.titan-embed-text-v2:0";         Use = "Vector embeddings" }
)

foreach ($m in $models) {
    $null = & aws bedrock get-foundation-model --model-identifier $m.Id 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "Model enabled: $($m.Id) ($($m.Use))"
    }
    else {
        Write-Fail "Model NOT enabled: $($m.Id) ($($m.Use))"
        Write-Info "Enable at: https://console.aws.amazon.com/bedrock/home#/modelaccess"
    }
}

# =============================================================
# 6. Python Environment
# =============================================================
Write-Header "6. Python Environment (for data generator)"

$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue }

if ($pyCmd) {
    $pyExe = $pyCmd.Source
    $pyVersion = & $pyExe --version 2>&1
    Write-Pass "Python installed: $pyVersion"

    $pyMinorRaw = & $pyExe -c "import sys; print(sys.version_info.minor)" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pyMinor = [int]"$pyMinorRaw".Trim()
        if ($pyMinor -ge 8) {
            Write-Pass "Python version is 3.8 or higher (compatible)"
        }
        else {
            Write-Warn "Python version is below 3.8 - upgrade recommended"
        }
    }

    # Check pip
    $pipCmd = Get-Command pip -ErrorAction SilentlyContinue
    if (-not $pipCmd) { $pipCmd = Get-Command pip3 -ErrorAction SilentlyContinue }

    if ($pipCmd) {
        Write-Pass "pip installed"

        $requiredPkgs = @("faker", "pandas", "openpyxl", "networkx", "boto3")
        $missingPkgs = @()

        foreach ($pkg in $requiredPkgs) {
            $null = & $pyExe -c "import $pkg" 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Pass "Package '$pkg' installed"
            }
            else {
                $missingPkgs += $pkg
                Write-Warn "Package '$pkg' not installed"
            }
        }

        if ($missingPkgs.Count -gt 0) {
            Write-Host ""
            Write-Info ("Install missing: pip install " + ($missingPkgs -join " "))
        }
    }
    else {
        Write-Warn "pip not found - needed to install Python packages"
    }
}
else {
    Write-Fail "Python not installed"
    Write-Info "Install: https://www.python.org/downloads/"
    Write-Info "Or run: winget install Python.Python.3.12"
}

# =============================================================
# 7. Quick S3 Write Test
# =============================================================
Write-Header "7. S3 Write Test (optional)"

$ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$testBucket = "graphrag-poc-test-$($script:AccountId)-$ts"
Write-Info "Attempting to create test bucket: $testBucket"

$null = & aws s3 mb "s3://$testBucket" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Pass "S3: Can create buckets"

    $testFile = Join-Path $env:TEMP "graphrag_test.txt"
    Set-Content -Path $testFile -Value "GraphRAG POC test" -Encoding utf8

    $null = & aws s3 cp $testFile "s3://$testBucket/test.txt" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "S3: Can upload files"
    }
    else {
        Write-Fail "S3: Cannot upload files (s3:PutObject denied)"
    }

    $null = & aws s3 rb "s3://$testBucket" --force 2>&1
    Remove-Item $testFile -ErrorAction SilentlyContinue
    Write-Info "Test bucket cleaned up"
}
else {
    Write-Warn "S3: Cannot create bucket (may need s3:CreateBucket permission)"
}

# =============================================================
# Summary
# =============================================================
Write-Host ""
Write-Host "============================================================"
Write-Host "  VALIDATION SUMMARY"
Write-Host "============================================================"
Write-Host "  Passed:   $($script:PassCount)" -ForegroundColor Green
Write-Host "  Failed:   $($script:FailCount)" -ForegroundColor Red
Write-Host "  Warnings: $($script:WarnCount)" -ForegroundColor Yellow
Write-Host "============================================================"

if ($script:FailCount -eq 0) {
    Write-Host ""
    Write-Host "  All critical checks passed! Ready for Milestone 0." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next steps:"
    Write-Host "    1. pip install faker pandas openpyxl networkx boto3"
    Write-Host "    2. python generate_fraud_data.py --output-dir .\data"
    Write-Host "    3. aws s3 mb s3://graphrag-fraud-poc-$($script:AccountId)"
    Write-Host "    4. aws s3 sync .\data\excel_for_bedrock\ s3://graphrag-fraud-poc-$($script:AccountId)/data/"
    Write-Host "    5. Open https://console.aws.amazon.com/bedrock/home#/knowledge-bases"
    Write-Host ""
}
elseif ($script:FailCount -le 2) {
    Write-Host ""
    Write-Host "  Some issues found - fix the FAIL items above first." -ForegroundColor Yellow
    Write-Host ""
}
else {
    Write-Host ""
    Write-Host "  Multiple failures - review and fix before starting." -ForegroundColor Red
    Write-Host ""
}

Write-Host "============================================================"
Write-Host ""