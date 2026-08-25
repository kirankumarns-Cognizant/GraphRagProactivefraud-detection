#!/usr/bin/env python3
"""Clean up all AWS resources created by the GraphRAG Fraud Detection POC.

Deletes in dependency order:
1. Bedrock Agent (aliases, action groups, KB associations, agent)
2. Bedrock Knowledge Base (data sources, KB)
3. Lambda functions
4. Neptune Analytics graphs (custom + KB)
5. SNS topic and subscriptions
6. S3 bucket and all objects
7. IAM roles and policies

Usage:
    python scripts/cleanup_resources.py --dry-run    # Preview
    python scripts/cleanup_resources.py              # Delete everything
    python scripts/cleanup_resources.py --neptune-only  # Just Neptune graphs
"""

import argparse
import logging
import time

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGION = "us-east-1"
BUCKET_NAME = "graphrag-fraud-poc-975049936238"
GRAPH_IDS = ["g-a6z57uuv00", "g-e0cmuhfo37"]
AGENT_ID = "GJUSMWNBMY"
KB_ID = "Z0ZI5NWJ4Z"
SNS_TOPIC_NAME = "graphrag-fraud-alerts"
LAMBDA_FUNCTIONS = [
    "graphrag-fraud-graph-query",
    "graphrag-fraud-risk-score",
    "graphrag-fraud-explain",
]
IAM_ROLES = [
    "NeptuneAnalytics-S3-Read-graphrag-fraud-poc",
    "graphrag-fraud-poc-bedrock-kb-role",
    "graphrag-fraud-poc-bedrock-agent-role",
    "graphrag-fraud-poc-lambda-role",
]


def delete_bedrock_agent(session: boto3.Session) -> None:
    """Delete Bedrock Agent and all its components."""
    bedrock = session.client("bedrock-agent")

    try:
        # Delete aliases first
        aliases = bedrock.list_agent_aliases(agentId=AGENT_ID)
        for alias in aliases.get("agentAliasSummaries", []):
            bedrock.delete_agent_alias(
                agentId=AGENT_ID, agentAliasId=alias["agentAliasId"]
            )
            logger.info("  Deleted alias: %s", alias["agentAliasName"])

        # Delete action groups
        ags = bedrock.list_agent_action_groups(agentId=AGENT_ID, agentVersion="DRAFT")
        for ag in ags.get("actionGroupSummaries", []):
            bedrock.delete_agent_action_group(
                agentId=AGENT_ID,
                agentVersion="DRAFT",
                actionGroupName=ag["actionGroupName"],
            )
            logger.info("  Deleted action group: %s", ag["actionGroupName"])

        # Disassociate KB
        kbs = bedrock.list_agent_knowledge_bases(agentId=AGENT_ID, agentVersion="DRAFT")
        for kb in kbs.get("agentKnowledgeBaseSummaries", []):
            bedrock.disassociate_agent_knowledge_base(
                agentId=AGENT_ID,
                agentVersion="DRAFT",
                knowledgeBaseId=kb["knowledgeBaseId"],
            )
            logger.info("  Disassociated KB: %s", kb["knowledgeBaseId"])

        # Delete agent
        bedrock.delete_agent(agentId=AGENT_ID, skipResourceInUseCheck=True)
        logger.info("Deleted Bedrock Agent: %s", AGENT_ID)
    except ClientError as e:
        if "ResourceNotFoundException" in str(e):
            logger.info("Bedrock Agent %s not found, skipping", AGENT_ID)
        else:
            logger.error("Error deleting agent: %s", e)


def delete_knowledge_base(session: boto3.Session) -> None:
    """Delete Bedrock Knowledge Base and data sources."""
    bedrock = session.client("bedrock-agent")

    try:
        # Delete data sources
        ds_list = bedrock.list_data_sources(knowledgeBaseId=KB_ID)
        for ds in ds_list.get("dataSourceSummaries", []):
            bedrock.delete_data_source(
                knowledgeBaseId=KB_ID, dataSourceId=ds["dataSourceId"]
            )
            logger.info("  Deleted data source: %s", ds["name"])

        # Delete KB
        bedrock.delete_knowledge_base(knowledgeBaseId=KB_ID)
        logger.info("Deleted Knowledge Base: %s", KB_ID)
    except ClientError as e:
        if "ResourceNotFoundException" in str(e):
            logger.info("Knowledge Base %s not found, skipping", KB_ID)
        else:
            logger.error("Error deleting KB: %s", e)


def delete_lambda_functions(session: boto3.Session) -> None:
    """Delete Lambda functions."""
    lambda_client = session.client("lambda")
    for name in LAMBDA_FUNCTIONS:
        try:
            lambda_client.delete_function(FunctionName=name)
            logger.info("Deleted Lambda: %s", name)
        except ClientError as e:
            if "ResourceNotFoundException" in str(e):
                logger.info("Lambda %s not found, skipping", name)
            else:
                logger.error("Error deleting Lambda %s: %s", name, e)


def delete_neptune_graphs(session: boto3.Session) -> None:
    """Delete Neptune Analytics graphs."""
    neptune = session.client("neptune-graph")
    for graph_id in GRAPH_IDS:
        try:
            resp = neptune.get_graph(graphIdentifier=graph_id)
            status = resp["status"]
            if status in ("AVAILABLE", "FAILED"):
                neptune.delete_graph(graphIdentifier=graph_id, skipSnapshot=True)
                logger.info("Deleting Neptune graph: %s (was %s)", graph_id, status)
            elif status == "DELETING":
                logger.info("Neptune graph %s already deleting", graph_id)
            else:
                logger.warning("Graph %s in state %s, cannot delete", graph_id, status)
        except ClientError as e:
            if "ResourceNotFoundException" in str(e):
                logger.info("Neptune graph %s not found, skipping", graph_id)
            else:
                logger.error("Error with graph %s: %s", graph_id, e)


def delete_sns_topic(session: boto3.Session) -> None:
    """Delete SNS topic and subscriptions."""
    sns = session.client("sns")
    try:
        topics = sns.list_topics()["Topics"]
        for topic in topics:
            if SNS_TOPIC_NAME in topic["TopicArn"]:
                # Delete subscriptions first
                subs = sns.list_subscriptions_by_topic(TopicArn=topic["TopicArn"])
                for sub in subs.get("Subscriptions", []):
                    if sub["SubscriptionArn"] != "PendingConfirmation":
                        sns.unsubscribe(SubscriptionArn=sub["SubscriptionArn"])
                        logger.info("  Unsubscribed: %s", sub["Protocol"])
                sns.delete_topic(TopicArn=topic["TopicArn"])
                logger.info("Deleted SNS topic: %s", topic["TopicArn"])
    except ClientError as e:
        logger.error("Error deleting SNS topic: %s", e)


def delete_s3_bucket(session: boto3.Session) -> None:
    """Delete S3 bucket and all objects."""
    s3 = session.client("s3")
    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
    except ClientError:
        logger.info("Bucket %s does not exist, skipping", BUCKET_NAME)
        return

    logger.info("Deleting all objects in %s...", BUCKET_NAME)
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=BUCKET_NAME):
        objects_to_delete = []
        for version in page.get("Versions", []):
            objects_to_delete.append(
                {"Key": version["Key"], "VersionId": version["VersionId"]}
            )
        for marker in page.get("DeleteMarkers", []):
            objects_to_delete.append(
                {"Key": marker["Key"], "VersionId": marker["VersionId"]}
            )
        if objects_to_delete:
            s3.delete_objects(
                Bucket=BUCKET_NAME, Delete={"Objects": objects_to_delete}
            )
            logger.info("  Deleted %d objects/versions", len(objects_to_delete))

    s3.delete_bucket(Bucket=BUCKET_NAME)
    logger.info("Deleted bucket: %s", BUCKET_NAME)


def delete_iam_roles(session: boto3.Session) -> None:
    """Delete IAM roles and their policies."""
    iam = session.client("iam")
    for role_name in IAM_ROLES:
        try:
            # Delete inline policies
            policies = iam.list_role_policies(RoleName=role_name)
            for policy_name in policies.get("PolicyNames", []):
                iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
                logger.info("  Deleted policy %s from %s", policy_name, role_name)
            # Detach managed policies
            attached = iam.list_attached_role_policies(RoleName=role_name)
            for policy in attached.get("AttachedPolicies", []):
                iam.detach_role_policy(
                    RoleName=role_name, PolicyArn=policy["PolicyArn"]
                )
            # Delete role
            iam.delete_role(RoleName=role_name)
            logger.info("Deleted role: %s", role_name)
        except ClientError as e:
            if "NoSuchEntity" in str(e):
                logger.info("Role %s not found, skipping", role_name)
            else:
                logger.error("Error deleting role %s: %s", role_name, e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up GraphRAG POC AWS resources")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be deleted")
    parser.add_argument("--neptune-only", action="store_true", help="Only delete Neptune graphs")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)

    if args.dry_run:
        logger.info("=== DRY RUN — no resources will be deleted ===")
        logger.info("Would delete: Bedrock Agent %s", AGENT_ID)
        logger.info("Would delete: Knowledge Base %s", KB_ID)
        logger.info("Would delete: Lambda functions %s", LAMBDA_FUNCTIONS)
        logger.info("Would delete: Neptune graphs %s", GRAPH_IDS)
        logger.info("Would delete: SNS topic %s", SNS_TOPIC_NAME)
        logger.info("Would delete: S3 bucket %s", BUCKET_NAME)
        logger.info("Would delete: IAM roles %s", IAM_ROLES)
        return

    if args.neptune_only:
        delete_neptune_graphs(session)
        logger.info("Neptune cleanup complete")
        return

    # Delete in dependency order
    logger.info("=== Starting full cleanup ===")

    logger.info("\n--- Step 1: Bedrock Agent ---")
    delete_bedrock_agent(session)

    logger.info("\n--- Step 2: Knowledge Base ---")
    delete_knowledge_base(session)

    logger.info("\n--- Step 3: Lambda Functions ---")
    delete_lambda_functions(session)

    logger.info("\n--- Step 4: Neptune Analytics Graphs ---")
    delete_neptune_graphs(session)

    logger.info("\n--- Step 5: SNS Topic ---")
    delete_sns_topic(session)

    logger.info("\n--- Step 6: S3 Bucket ---")
    delete_s3_bucket(session)

    logger.info("\n--- Step 7: IAM Roles ---")
    delete_iam_roles(session)

    logger.info("\n=== Cleanup complete ===")
    logger.info("Verify in AWS Cost Explorer that no charges persist after 24 hours.")


if __name__ == "__main__":
    main()
