#!/usr/bin/env python3
"""Deploy Lambda functions for Bedrock Agent action groups.

Creates:
1. Lambda execution role with Neptune + Bedrock permissions
2. Three Lambda functions: graph_query, risk_score, explain
3. Resource-based policy for Bedrock Agent invocation

Usage:
    python scripts/deploy_lambdas.py
    python scripts/deploy_lambdas.py --delete  # Cleanup
"""

import argparse
import io
import json
import logging
import os
import time
import zipfile

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGION = "us-east-1"
GRAPH_ID = "g-a6z57uuv00"
LAMBDA_ROLE_NAME = "graphrag-fraud-poc-lambda-role"
FUNCTION_PREFIX = "graphrag-fraud"
TAGS = {
    "Project": "graphrag-fraud-poc",
    "Environment": "poc",
    "Owner": "118797",
    "CostCenter": "graphrag-rd",
}

LAMBDA_FUNCTIONS = [
    {
        "name": f"{FUNCTION_PREFIX}-graph-query",
        "handler": "handler.lambda_handler",
        "source_dir": os.path.join("lambdas", "graph_query"),
        "description": "GraphRAG fraud detection — graph traversal queries on Neptune Analytics",
        "timeout": 30,
        "memory": 256,
    },
    {
        "name": f"{FUNCTION_PREFIX}-risk-score",
        "handler": "handler.lambda_handler",
        "source_dir": os.path.join("lambdas", "risk_score"),
        "description": "GraphRAG fraud detection — network-based risk scoring",
        "timeout": 30,
        "memory": 256,
    },
    {
        "name": f"{FUNCTION_PREFIX}-explain",
        "handler": "handler.lambda_handler",
        "source_dir": os.path.join("lambdas", "explain"),
        "description": "GraphRAG fraud detection — explainability with evidence chains",
        "timeout": 60,
        "memory": 256,
    },
]


def get_account_id(session: boto3.Session) -> str:
    """Get AWS account ID from STS."""
    return session.client("sts").get_caller_identity()["Account"]


def create_lambda_role(session: boto3.Session, account_id: str) -> str:
    """Create IAM execution role for Lambda functions."""
    iam = session.client("iam")

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    execution_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CloudWatchLogs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": f"arn:aws:logs:{REGION}:{account_id}:*",
            },
            {
                "Sid": "NeptuneAccess",
                "Effect": "Allow",
                "Action": [
                    "neptune-graph:ExecuteQuery",
                    "neptune-graph:ReadDataViaQuery",
                    "neptune-graph:GetGraph",
                ],
                "Resource": f"arn:aws:neptune-graph:{REGION}:{account_id}:graph/{GRAPH_ID}",
            },
            {
                "Sid": "BedrockModelInvoke",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel"],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/anthropic.*",
                    f"arn:aws:bedrock:*:{account_id}:inference-profile/us.anthropic.*",
                ],
            },
        ],
    }

    try:
        resp = iam.create_role(
            RoleName=LAMBDA_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for GraphRAG fraud detection Lambda functions",
            Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()],
        )
        role_arn = resp["Role"]["Arn"]
        logger.info("Created Lambda role: %s", role_arn)
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = f"arn:aws:iam::{account_id}:role/{LAMBDA_ROLE_NAME}"
            logger.info("Lambda role already exists: %s", role_arn)
        else:
            raise

    iam.put_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyName="LambdaExecutionPolicy",
        PolicyDocument=json.dumps(execution_policy),
    )

    logger.info("Waiting 10s for IAM propagation...")
    time.sleep(10)
    return role_arn


def create_zip_package(source_dir: str) -> bytes:
    """Create a zip deployment package from a Lambda source directory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(source_dir):
            for f in files:
                if f.endswith(".py"):
                    filepath = os.path.join(root, f)
                    arcname = os.path.relpath(filepath, source_dir)
                    zf.write(filepath, arcname)
    return buf.getvalue()


def deploy_function(
    lambda_client: "boto3.client",
    func_config: dict,
    role_arn: str,
    account_id: str,
) -> str:
    """Deploy or update a Lambda function."""
    name = func_config["name"]
    zip_bytes = create_zip_package(func_config["source_dir"])
    logger.info("Package size for %s: %d bytes", name, len(zip_bytes))

    env_vars = {
        "NEPTUNE_GRAPH_ID": GRAPH_ID,
        "AWS_REGION_OVERRIDE": REGION,
    }

    try:
        resp = lambda_client.create_function(
            FunctionName=name,
            Runtime="python3.12",
            Role=role_arn,
            Handler=func_config["handler"],
            Code={"ZipFile": zip_bytes},
            Description=func_config["description"],
            Timeout=func_config["timeout"],
            MemorySize=func_config["memory"],
            Environment={"Variables": env_vars},
            Tags=TAGS,
        )
        func_arn = resp["FunctionArn"]
        logger.info("Created function: %s", func_arn)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            # Function exists — update code
            lambda_client.update_function_code(
                FunctionName=name,
                ZipFile=zip_bytes,
            )
            # Wait for code update
            time.sleep(3)
            lambda_client.update_function_configuration(
                FunctionName=name,
                Role=role_arn,
                Handler=func_config["handler"],
                Description=func_config["description"],
                Timeout=func_config["timeout"],
                MemorySize=func_config["memory"],
                Environment={"Variables": env_vars},
            )
            func_arn = f"arn:aws:lambda:{REGION}:{account_id}:function:{name}"
            logger.info("Updated function: %s", func_arn)
        else:
            raise

    # Add Bedrock Agent invoke permission
    try:
        lambda_client.add_permission(
            FunctionName=name,
            StatementId="AllowBedrockAgentInvoke",
            Action="lambda:InvokeFunction",
            Principal="bedrock.amazonaws.com",
            SourceAccount=account_id,
        )
        logger.info("Added Bedrock invoke permission for %s", name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            logger.info("Bedrock invoke permission already exists for %s", name)
        else:
            raise

    return func_arn


def delete_functions(session: boto3.Session) -> None:
    """Delete all deployed Lambda functions and role."""
    lambda_client = session.client("lambda")
    iam = session.client("iam")

    for func in LAMBDA_FUNCTIONS:
        try:
            lambda_client.delete_function(FunctionName=func["name"])
            logger.info("Deleted function: %s", func["name"])
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                logger.error("Failed to delete %s: %s", func["name"], e)

    try:
        iam.delete_role_policy(RoleName=LAMBDA_ROLE_NAME, PolicyName="LambdaExecutionPolicy")
        iam.delete_role(RoleName=LAMBDA_ROLE_NAME)
        logger.info("Deleted role: %s", LAMBDA_ROLE_NAME)
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            logger.error("Failed to delete role: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Lambda functions for Bedrock Agent")
    parser.add_argument("--delete", action="store_true", help="Delete all functions and role")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)
    account_id = get_account_id(session)

    if args.delete:
        delete_functions(session)
        return

    # Create role
    role_arn = create_lambda_role(session, account_id)

    # Deploy functions
    lambda_client = session.client("lambda")
    arns = {}
    for func in LAMBDA_FUNCTIONS:
        arn = deploy_function(lambda_client, func, role_arn, account_id)
        arns[func["name"]] = arn

    logger.info("")
    logger.info("=== DEPLOYMENT COMPLETE ===")
    for name, arn in arns.items():
        logger.info("  %s: %s", name, arn)
    logger.info("")
    logger.info("Next: python scripts/create_bedrock_agent.py")


if __name__ == "__main__":
    main()
