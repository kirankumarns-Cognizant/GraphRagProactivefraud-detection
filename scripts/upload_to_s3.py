#!/usr/bin/env python3
"""Upload clean data files to S3 bucket for Bedrock Knowledge Base ingestion.

Only uploads from data/excel_for_bedrock/ (no fraud labels).
Never uploads from csv_labeled/.
"""

import argparse
import logging
import os
import sys

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BUCKET_NAME = "graphrag-fraud-poc-975049936238"
REGION = "us-east-1"
TAGS = {
    "Project": "graphrag-fraud-poc",
    "Environment": "poc",
    "Owner": "118797",
    "CostCenter": "graphrag-rd",
}

# Columns that must NEVER appear in uploaded files
FORBIDDEN_COLUMNS = {"is_fraud", "fraud_pattern", "fraud_ring", "fraud_type"}


def create_bucket(s3_client: "boto3.client") -> str:
    """Create S3 bucket with public access blocked and versioning enabled."""
    try:
        s3_client.head_bucket(Bucket=BUCKET_NAME)
        logger.info("Bucket %s already exists", BUCKET_NAME)
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            logger.info("Creating bucket %s in %s", BUCKET_NAME, REGION)
            # us-east-1 doesn't use LocationConstraint
            s3_client.create_bucket(Bucket=BUCKET_NAME)
            logger.info("Bucket created successfully")
        else:
            raise

    # Block all public access
    s3_client.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    logger.info("Public access blocked on %s", BUCKET_NAME)

    # Enable versioning
    s3_client.put_bucket_versioning(
        Bucket=BUCKET_NAME,
        VersioningConfiguration={"Status": "Enabled"},
    )
    logger.info("Versioning enabled on %s", BUCKET_NAME)

    # Tag bucket
    tag_set = [{"Key": k, "Value": v} for k, v in TAGS.items()]
    s3_client.put_bucket_tagging(
        Bucket=BUCKET_NAME,
        Tagging={"TagSet": tag_set},
    )
    logger.info("Tags applied to %s", BUCKET_NAME)

    return BUCKET_NAME


def validate_file_no_fraud_labels(filepath: str) -> bool:
    """Check that file does not contain forbidden fraud label columns."""
    import pandas as pd

    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == ".csv":
            df = pd.read_csv(filepath, nrows=0)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(filepath, nrows=0)
        else:
            return True  # Non-tabular files are fine

        found = set(c.lower() for c in df.columns) & FORBIDDEN_COLUMNS
        if found:
            logger.error("SECURITY: %s contains forbidden columns: %s", filepath, found)
            return False
        return True
    except Exception as e:
        logger.warning("Could not validate %s: %s", filepath, e)
        return True


def upload_directory(s3_client: "boto3.client", local_dir: str, s3_prefix: str) -> int:
    """Upload all files from local_dir to s3://BUCKET_NAME/s3_prefix/."""
    count = 0
    for filename in sorted(os.listdir(local_dir)):
        filepath = os.path.join(local_dir, filename)
        if not os.path.isfile(filepath):
            continue

        if not validate_file_no_fraud_labels(filepath):
            logger.error("BLOCKED upload of %s due to fraud label leak", filepath)
            sys.exit(1)

        s3_key = f"{s3_prefix}/{filename}"
        logger.info("Uploading %s -> s3://%s/%s", filepath, BUCKET_NAME, s3_key)
        s3_client.upload_file(filepath, BUCKET_NAME, s3_key)
        count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload fraud POC data to S3")
    parser.add_argument("--data-dir", default="data", help="Root data directory")
    parser.add_argument("--include-blog-sample", action="store_true",
                        help="Also upload AWS blog sample files")
    parser.add_argument("--include-sars", action="store_true",
                        help="Also upload SAR documents")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be uploaded without uploading")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)
    s3 = session.client("s3")

    if args.dry_run:
        logger.info("DRY RUN - no files will be uploaded")
        bedrock_dir = os.path.join(args.data_dir, "excel_for_bedrock")
        for f in sorted(os.listdir(bedrock_dir)):
            logger.info("  Would upload: %s -> excel_for_bedrock/%s", f, f)
        return

    # Create bucket
    create_bucket(s3)

    # Upload excel_for_bedrock (primary data for KB)
    bedrock_dir = os.path.join(args.data_dir, "excel_for_bedrock")
    count = upload_directory(s3, bedrock_dir, "excel_for_bedrock")
    logger.info("Uploaded %d files from excel_for_bedrock/", count)

    # Optionally upload blog sample files
    if args.include_blog_sample:
        blog_dir = os.path.join(args.data_dir, "aws_blog_sample")
        if os.path.isdir(blog_dir):
            count = upload_directory(s3, blog_dir, "aws_blog_sample")
            logger.info("Uploaded %d blog sample files", count)

    # Optionally upload SAR documents
    if args.include_sars:
        sar_dir = os.path.join(args.data_dir, "sar_documents")
        if os.path.isdir(sar_dir):
            count = upload_directory(s3, sar_dir, "sar_documents")
            logger.info("Uploaded %d SAR documents", count)

    logger.info("Upload complete. Bucket: s3://%s", BUCKET_NAME)


if __name__ == "__main__":
    main()
