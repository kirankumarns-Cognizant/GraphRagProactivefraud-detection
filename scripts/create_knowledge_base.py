#!/usr/bin/env python3
"""Create Bedrock Knowledge Base with Neptune Analytics GraphRAG.

REQUIRES: Bedrock model access (Claude Haiku, Titan Embeddings V2)
Run this after Bedrock access is granted.

Creates:
1. IAM service role for Bedrock KB
2. Bedrock Knowledge Base with Neptune Analytics vector store
3. S3 data source pointing to excel_for_bedrock/
4. Kicks off data sync
"""

import json
import logging
import time

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGION = "us-east-1"
BUCKET_NAME = "graphrag-fraud-poc-975049936238"
GRAPH_ID = "g-e0cmuhfo37"  # Empty graph for Bedrock KB (separate from custom fraud graph)
KB_NAME = "graphrag-fraud-poc"
KB_ROLE_NAME = "graphrag-fraud-poc-bedrock-kb-role"
TAGS = {
    "Project": "graphrag-fraud-poc",
    "Environment": "poc",
    "Owner": "118797",
    "CostCenter": "graphrag-rd",
}


def get_account_id(session: boto3.Session) -> str:
    """Get AWS account ID from STS."""
    return session.client("sts").get_caller_identity()["Account"]


def get_graph_arn(session: boto3.Session) -> str:
    """Get the Neptune Analytics graph ARN."""
    neptune = session.client("neptune-graph")
    resp = neptune.get_graph(graphIdentifier=GRAPH_ID)
    return resp["arn"]


def create_kb_service_role(session: boto3.Session, account_id: str, graph_arn: str) -> str:
    """Create IAM service role for Bedrock Knowledge Base."""
    iam = session.client("iam")

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                },
            }
        ],
    }

    # Permissions the KB needs: S3 read, Neptune read/write, Bedrock model invoke
    kb_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "S3Access",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": [
                    f"arn:aws:s3:::{BUCKET_NAME}",
                    f"arn:aws:s3:::{BUCKET_NAME}/*",
                ],
            },
            {
                "Sid": "NeptuneAccess",
                "Effect": "Allow",
                "Action": [
                    "neptune-graph:GetGraph",
                    "neptune-graph:ExecuteQuery",
                    "neptune-graph:ListGraphs",
                    "neptune-graph:ReadDataViaQuery",
                    "neptune-graph:WriteDataViaQuery",
                    "neptune-graph:DeleteDataViaQuery",
                ],
                "Resource": graph_arn,
            },
            {
                "Sid": "BedrockModelInvoke",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel"],
                "Resource": [
                    "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0",
                    "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
                    "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
                    f"arn:aws:bedrock:us-east-1:{account_id}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
                    f"arn:aws:bedrock:us-east-1:{account_id}:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0",
                ],
            },
        ],
    }

    try:
        resp = iam.create_role(
            RoleName=KB_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Service role for Bedrock KB with Neptune Analytics GraphRAG",
            Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()],
        )
        role_arn = resp["Role"]["Arn"]
        logger.info("Created KB service role: %s", role_arn)
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = f"arn:aws:iam::{account_id}:role/{KB_ROLE_NAME}"
            logger.info("KB service role already exists: %s", role_arn)
        else:
            raise

    iam.put_role_policy(
        RoleName=KB_ROLE_NAME,
        PolicyName="BedrockKBAccess",
        PolicyDocument=json.dumps(kb_policy),
    )
    logger.info("Attached KB access policy")

    logger.info("Waiting 10s for IAM propagation...")
    time.sleep(10)
    return role_arn


def create_knowledge_base(session: boto3.Session, role_arn: str, graph_arn: str) -> str:
    """Create Bedrock Knowledge Base with Neptune Analytics storage."""
    bedrock_agent = session.client("bedrock-agent")

    try:
        resp = bedrock_agent.create_knowledge_base(
            name=KB_NAME,
            description="GraphRAG-based fraud detection knowledge base with Neptune Analytics",
            roleArn=role_arn,
            knowledgeBaseConfiguration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": f"arn:aws:bedrock:{REGION}::foundation-model/amazon.titan-embed-text-v2:0",
                },
            },
            storageConfiguration={
                "type": "NEPTUNE_ANALYTICS",
                "neptuneAnalyticsConfiguration": {
                    "graphArn": graph_arn,
                    "fieldMapping": {
                        "textField": "AMAZON_BEDROCK_TEXT_CHUNK",
                        "metadataField": "AMAZON_BEDROCK_METADATA",
                    },
                },
            },
            tags=TAGS,
        )
        kb_id = resp["knowledgeBase"]["knowledgeBaseId"]
        logger.info("Created Knowledge Base: %s (id=%s)", KB_NAME, kb_id)
        return kb_id
    except ClientError as e:
        logger.error("Failed to create KB: %s", e)
        raise


def create_data_source(session: boto3.Session, kb_id: str) -> str:
    """Create S3 data source for the Knowledge Base."""
    bedrock_agent = session.client("bedrock-agent")

    resp = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name="fraud-poc-s3-data",
        description="Synthetic fraud data from S3",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{BUCKET_NAME}",
                "inclusionPrefixes": ["excel_for_bedrock/"],
            },
        },
        contextEnrichmentConfiguration={
            "type": "BEDROCK_FOUNDATION_MODEL",
            "bedrockFoundationModelConfiguration": {
                "modelArn": f"arn:aws:bedrock:{REGION}::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
                "enrichmentStrategyConfiguration": {
                    "method": "CHUNK_ENTITY_EXTRACTION",
                },
            },
        },
    )
    ds_id = resp["dataSource"]["dataSourceId"]
    logger.info("Created data source: %s", ds_id)
    return ds_id


def start_sync(session: boto3.Session, kb_id: str, ds_id: str) -> str:
    """Start data source sync (ingestion)."""
    bedrock_agent = session.client("bedrock-agent")

    resp = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
    )
    job_id = resp["ingestionJob"]["ingestionJobId"]
    logger.info("Started sync job: %s", job_id)
    return job_id


def main() -> None:
    session = boto3.Session(region_name=REGION)
    account_id = get_account_id(session)
    logger.info("Account: %s", account_id)

    # Get graph ARN
    graph_arn = get_graph_arn(session)
    logger.info("Graph ARN: %s", graph_arn)

    # Create service role
    role_arn = create_kb_service_role(session, account_id, graph_arn)

    # Create Knowledge Base
    kb_id = create_knowledge_base(session, role_arn, graph_arn)

    # Create data source
    ds_id = create_data_source(session, kb_id)

    # Start sync
    job_id = start_sync(session, kb_id, ds_id)

    logger.info("")
    logger.info("=== SUMMARY ===")
    logger.info("Knowledge Base ID: %s", kb_id)
    logger.info("Data Source ID: %s", ds_id)
    logger.info("Sync Job ID: %s", job_id)
    logger.info("")
    logger.info("Monitor sync progress in the Bedrock console or with:")
    logger.info("  aws bedrock-agent get-ingestion-job --knowledge-base-id %s --data-source-id %s --ingestion-job-id %s",
                kb_id, ds_id, job_id)


if __name__ == "__main__":
    main()
