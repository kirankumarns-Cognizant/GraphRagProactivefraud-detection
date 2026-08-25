#!/usr/bin/env python3
"""Create Neptune Analytics graph and import data from S3.

Creates:
1. IAM role for Neptune Analytics to read from S3
2. Neptune Analytics graph with imported node/edge data

Estimated cost: Neptune Analytics 4 vCPU ~$0.28/hr (~$6.72/day)
"""

import json
import logging
import time

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGION = "us-east-1"
BUCKET_NAME = "graphrag-fraud"
GRAPH_NAME = "myfraud-detection-graph"
ROLE_NAME = "NeptuneAnalytics-S3-Read-graphrag-fraud"
TAGS = {
    "Project": "graphrag-fraud-poc",
    "Environment": "poc",
    "Owner": "884412",
    "CostCenter": "graphrag-rd",
}


def get_account_id(session: boto3.Session) -> str:
    """Get AWS account ID from STS."""
    sts = session.client("sts")
    return sts.get_caller_identity()["Account"]


def create_neptune_s3_role(session: boto3.Session, account_id: str) -> str:
    """Create IAM role for Neptune Analytics to read from S3."""
    iam = session.client("iam")

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "neptune-graph.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:ListBucket",
                ],
                "Resource": [
                    f"arn:aws:s3:::{BUCKET_NAME}",
                    f"arn:aws:s3:::{BUCKET_NAME}/*",
                ],
            }
        ],
    }

    # Create role
    try:
        resp = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Allows Neptune Analytics to read from S3 for graph import",
            Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()],
        )
        role_arn = resp["Role"]["Arn"]
        logger.info("Created IAM role: %s", role_arn)
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"
            logger.info("IAM role already exists: %s", role_arn)
        else:
            raise

    # Attach inline policy
    policy_name = "NeptuneS3ReadAccess"
    try:
        iam.put_role_policy(
            RoleName=ROLE_NAME,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(s3_policy),
        )
        logger.info("Attached S3 read policy to role")
    except ClientError as e:
        logger.error("Failed to attach policy: %s", e)
        raise

    # Wait for role propagation
    logger.info("Waiting 10s for IAM role propagation...")
    time.sleep(10)

    return role_arn


def create_graph_with_import(session: boto3.Session, role_arn: str) -> dict:
    """Create Neptune Analytics graph and import data from S3."""
    neptune = session.client("neptune-graph")

    # Check if graph already exists (skip if DELETING)
    try:
        graphs = neptune.list_graphs(maxResults=50)
        for g in graphs.get("graphs", []):
            if g["name"] == GRAPH_NAME:
                if g["status"] == "DELETING":
                    logger.info("Graph '%s' is DELETING (id=%s), will create new one",
                                GRAPH_NAME, g["id"])
                else:
                    logger.info("Graph '%s' already exists (id=%s, status=%s)",
                                GRAPH_NAME, g["id"], g["status"])
                    return g
    except ClientError as e:
        logger.warning("Could not list graphs: %s", e)

    # Create graph with import from S3
    # Neptune Analytics minimum: 4 vCPUs (~$0.28/hr)
    logger.info("Creating Neptune Analytics graph '%s' with S3 import...", GRAPH_NAME)
    logger.info("  Source: s3://%s/neptune_bulk_load/", BUCKET_NAME)
    logger.info("  Estimated cost: ~$0.28/hr (~$6.72/day)")

    try:
        resp = neptune.create_graph_using_import_task(
            graphName=GRAPH_NAME,
            tags=TAGS,
            publicConnectivity=True,
            minProvisionedMemory=32,  # Minimum for 4 vCPU - 32 GiB
            vectorSearchConfiguration={"dimension": 1024},  # Required for Bedrock KB GraphRAG
            source=f"s3://{BUCKET_NAME}/neptune_bulk_load/",
            format="CSV",
            roleArn=role_arn,
        )
        graph_id = resp["graphId"]
        task_id = resp["taskId"]
        logger.info("Graph creation started: graphId=%s, taskId=%s", graph_id, task_id)
        logger.info("Status: %s", resp["status"])
        return resp
    except ClientError as e:
        logger.error("Failed to create graph: %s", e)
        raise


def wait_for_graph(session: boto3.Session, graph_id: str, timeout_minutes: int = 30) -> dict:
    """Poll until graph creation and import completes."""
    neptune = session.client("neptune-graph")
    start = time.time()
    timeout_secs = timeout_minutes * 60

    while True:
        elapsed = time.time() - start
        if elapsed > timeout_secs:
            logger.error("Timeout waiting for graph after %d minutes", timeout_minutes)
            break

        try:
            resp = neptune.get_graph(graphIdentifier=graph_id)
            status = resp["status"]
            logger.info("Graph %s status: %s (%.0fs elapsed)", graph_id, status, elapsed)

            if status == "AVAILABLE":
                logger.info("Graph is AVAILABLE!")
                logger.info("  Endpoint: %s", resp.get("endpoint", "N/A"))
                return resp
            elif status in ("FAILED", "DELETING"):
                logger.error("Graph entered terminal state: %s", status)
                return resp
        except ClientError as e:
            logger.warning("Error checking graph status: %s", e)

        time.sleep(30)

    return {}


def main() -> None:
    session = boto3.Session(region_name=REGION)
    account_id = get_account_id(session)
    logger.info("Account: %s", account_id)

    # Step 1: Create IAM role
    role_arn = create_neptune_s3_role(session, account_id)

    # Step 2: Create graph with import
    result = create_graph_with_import(session, role_arn)
    graph_id = result.get("graphId") or result.get("id")

    if not graph_id:
        logger.error("No graph ID returned")
        return

    # Step 3: Wait for completion
    logger.info("Waiting for graph creation + data import to complete...")
    final = wait_for_graph(session, graph_id)

    if final.get("status") == "AVAILABLE":
        logger.info("SUCCESS: Graph '%s' is ready", GRAPH_NAME)
        logger.info("  Graph ID: %s", graph_id)
        logger.info("  Endpoint: %s", final.get("endpoint", "N/A"))
        logger.info("")
        logger.info("IMPORTANT: Neptune Analytics costs ~$0.28/hr while running.")
        logger.info("Run 'python scripts/cleanup_resources.py' to delete when done.")
    else:
        logger.warning("Graph status: %s — check AWS console", final.get("status", "UNKNOWN"))


if __name__ == "__main__":
    main()
