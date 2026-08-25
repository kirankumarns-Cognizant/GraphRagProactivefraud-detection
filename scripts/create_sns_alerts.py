#!/usr/bin/env python3
"""Create SNS topic for fraud alert notifications.

Creates:
1. SNS topic 'graphrag-fraud-alerts'
2. Email subscription (user provides email)

Usage:
    python scripts/create_sns_alerts.py --email user@example.com
"""

import argparse
import logging

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGION = "us-east-1"
TOPIC_NAME = "graphrag-fraud-alerts"
TAGS = {
    "Project": "graphrag-fraud-poc",
    "Environment": "poc",
    "Owner": "884412",
    "CostCenter": "graphrag-rd",
}


def create_topic(session: boto3.Session) -> str:
    """Create SNS topic for fraud alerts."""
    sns = session.client("sns")

    try:
        resp = sns.create_topic(
            Name=TOPIC_NAME,
            Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()],
        )
        topic_arn = resp["TopicArn"]
        logger.info("Created SNS topic: %s", topic_arn)
        return topic_arn
    except ClientError as e:
        logger.error("Failed to create topic: %s", e)
        raise


def subscribe_email(session: boto3.Session, topic_arn: str, email: str) -> str:
    """Subscribe an email address to the topic."""
    sns = session.client("sns")

    try:
        resp = sns.subscribe(
            TopicArn=topic_arn,
            Protocol="email",
            Endpoint=email,
        )
        sub_arn = resp["SubscriptionArn"]
        logger.info("Subscribed %s to topic (confirmation pending)", email)
        logger.info("CHECK YOUR EMAIL and confirm the subscription!")
        return sub_arn
    except ClientError as e:
        logger.error("Failed to subscribe: %s", e)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Create SNS fraud alert topic")
    parser.add_argument("--email", required=True, help="Email address to subscribe")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)

    topic_arn = create_topic(session)
    subscribe_email(session, topic_arn, args.email)

    logger.info("")
    logger.info("=== SETUP COMPLETE ===")
    logger.info("Topic ARN: %s", topic_arn)
    logger.info("")
    logger.info("Use this ARN in the transaction simulator:")
    logger.info("  python scripts/simulate_transactions.py --graph-id <ID> --sns-topic-arn %s", topic_arn)
    logger.info("")
    logger.info("Or set as environment variable:")
    logger.info("  export SNS_TOPIC_ARN=%s", topic_arn)


if __name__ == "__main__":
    main()
