#!/usr/bin/env python3
"""Create Bedrock Agent with action groups for fraud investigation.

REQUIRES: Bedrock model access + Lambda functions deployed
Run this after:
1. Bedrock access is granted
2. Knowledge Base is created (create_knowledge_base.py)
3. Lambda functions are deployed

Creates:
1. Bedrock Agent with Claude Sonnet as reasoning model
2. Three action groups: GraphQuery, RiskScore, Explain
3. Knowledge Base association
"""

import json
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGION = "us-east-1"
AGENT_NAME = "graphrag-fraud-analyst"
SONNET_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
AGENT_ROLE_NAME = "graphrag-fraud-poc-bedrock-agent-role"
TAGS = {
    "Project": "graphrag-fraud-poc",
    "Environment": "poc",
    "Owner": "118797",
    "CostCenter": "graphrag-rd",
}

AGENT_INSTRUCTION = """You are a senior fraud analyst assistant specializing in financial fraud
detection using graph-based analysis. You have access to a financial transaction knowledge graph
that contains customers, accounts, devices, merchants, IP addresses, and their relationships.

Your capabilities:
1. **Graph Query**: Traverse the knowledge graph to find connected entities, shared devices,
   and multi-hop relationships that indicate coordinated fraud.
2. **Risk Scoring**: Compute network-based risk scores for accounts using device sharing patterns,
   merchant risk exposure, fraud proximity, and transaction velocity.
3. **Explainability**: Generate human-readable explanations of why an entity is flagged,
   with complete evidence chains and recommended actions.

When investigating fraud:
- Always start by looking up the entity and its immediate connections
- Explore shared devices — they are the strongest fraud indicator in this dataset
- Check multi-hop connections (up to 3 hops) to find fraud ring members
- Provide confidence levels (HIGH/MEDIUM/LOW) with every assessment
- Include the evidence chain: which entities, which relationships, which patterns
- Recommend specific next steps for the investigation team

Output format for every investigation:
1. **Summary**: One-sentence finding
2. **Evidence Chain**: Step-by-step path through the graph
3. **Risk Level**: HIGH/MEDIUM/LOW with justification
4. **Connected Entities**: List of related accounts/devices/merchants
5. **Recommended Action**: What the fraud team should do next
"""

# OpenAPI schema for action groups
GRAPH_QUERY_SCHEMA = {
    "openapi": "3.0.0",
    "info": {"title": "Graph Query API", "version": "1.0.0"},
    "paths": {
        "/entity_lookup": {
            "post": {
                "operationId": "entity_lookup",
                "description": "Look up an entity by its ID (e.g., A0042, C0073, D0007)",
                "parameters": [
                    {"name": "entity_id", "in": "query", "required": True,
                     "schema": {"type": "string"},
                     "description": "Entity ID to look up (e.g., A0042 for account, C0073 for customer, D0007 for device)"}
                ],
                "responses": {"200": {"description": "Entity details"}},
            }
        },
        "/multi_hop": {
            "post": {
                "operationId": "multi_hop",
                "description": "Find all entities connected within N hops of a starting entity",
                "parameters": [
                    {"name": "entity_id", "in": "query", "required": True,
                     "schema": {"type": "string"},
                     "description": "Starting entity ID"},
                    {"name": "max_hops", "in": "query", "required": False,
                     "schema": {"type": "integer", "default": 3},
                     "description": "Maximum number of hops (1-5)"},
                    {"name": "limit", "in": "query", "required": False,
                     "schema": {"type": "integer", "default": 50},
                     "description": "Maximum results to return"},
                ],
                "responses": {"200": {"description": "Connected entities with hop distances"}},
            }
        },
        "/shared_devices": {
            "post": {
                "operationId": "shared_devices",
                "description": "Find all devices shared between multiple accounts — key fraud indicator",
                "parameters": [],
                "responses": {"200": {"description": "Shared devices with account lists"}},
            }
        },
        "/account_network": {
            "post": {
                "operationId": "account_network",
                "description": "Get complete network of an account: devices, merchants, shared accounts",
                "parameters": [
                    {"name": "account_id", "in": "query", "required": True,
                     "schema": {"type": "string"},
                     "description": "Account ID (e.g., A0042)"}
                ],
                "responses": {"200": {"description": "Account network details"}},
            }
        },
        "/fraud_ring": {
            "post": {
                "operationId": "fraud_ring",
                "description": "Find potential fraud ring members connected via shared devices and known associates",
                "parameters": [
                    {"name": "entity_id", "in": "query", "required": True,
                     "schema": {"type": "string"},
                     "description": "Starting entity ID"},
                    {"name": "max_hops", "in": "query", "required": False,
                     "schema": {"type": "integer", "default": 3},
                     "description": "Maximum hops to traverse"},
                ],
                "responses": {"200": {"description": "Fraud ring members with distances"}},
            }
        },
        "/shortest_path": {
            "post": {
                "operationId": "shortest_path",
                "description": "Find shortest path between two entities in the graph",
                "parameters": [
                    {"name": "entity_a", "in": "query", "required": True,
                     "schema": {"type": "string"}, "description": "First entity ID"},
                    {"name": "entity_b", "in": "query", "required": True,
                     "schema": {"type": "string"}, "description": "Second entity ID"},
                    {"name": "max_hops", "in": "query", "required": False,
                     "schema": {"type": "integer", "default": 6},
                     "description": "Maximum path length"},
                ],
                "responses": {"200": {"description": "Path with nodes and edge types"}},
            }
        },
    },
}

RISK_SCORE_SCHEMA = {
    "openapi": "3.0.0",
    "info": {"title": "Risk Score API", "version": "1.0.0"},
    "paths": {
        "/compute_risk": {
            "post": {
                "operationId": "compute_risk",
                "description": "Compute network-based risk score for an account based on device sharing, merchant risk, fraud proximity, and transaction velocity",
                "parameters": [
                    {"name": "account_id", "in": "query", "required": True,
                     "schema": {"type": "string"},
                     "description": "Account ID to score (e.g., A0042)"}
                ],
                "responses": {"200": {"description": "Risk score with factor breakdown"}},
            }
        },
    },
}

EXPLAIN_SCHEMA = {
    "openapi": "3.0.0",
    "info": {"title": "Explain API", "version": "1.0.0"},
    "paths": {
        "/explain_entity": {
            "post": {
                "operationId": "explain_entity",
                "description": "Generate a human-readable explanation of why an entity is flagged for fraud, with evidence chain and recommended actions",
                "parameters": [
                    {"name": "entity_id", "in": "query", "required": True,
                     "schema": {"type": "string"},
                     "description": "Entity ID to explain"},
                    {"name": "max_hops", "in": "query", "required": False,
                     "schema": {"type": "integer", "default": 3},
                     "description": "Maximum hops for evidence gathering"},
                ],
                "responses": {"200": {"description": "Explanation with evidence and risk level"}},
            }
        },
    },
}


def get_account_id(session: boto3.Session) -> str:
    """Get AWS account ID from STS."""
    return session.client("sts").get_caller_identity()["Account"]


def create_agent_role(session: boto3.Session, account_id: str) -> str:
    """Create IAM role for Bedrock Agent."""
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

    agent_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BedrockModelInvoke",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel", "bedrock:GetInferenceProfile"],
                "Resource": [
                    f"arn:aws:bedrock:*::foundation-model/anthropic.*",
                    f"arn:aws:bedrock:*:{account_id}:inference-profile/us.anthropic.*",
                ],
            },
            {
                "Sid": "LambdaInvoke",
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": f"arn:aws:lambda:{REGION}:{account_id}:function:graphrag-fraud-*",
            },
            {
                "Sid": "BedrockKBRetrieve",
                "Effect": "Allow",
                "Action": [
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                ],
                "Resource": f"arn:aws:bedrock:{REGION}:{account_id}:knowledge-base/*",
            },
        ],
    }

    try:
        resp = iam.create_role(
            RoleName=AGENT_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Service role for Bedrock fraud analyst agent",
            Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()],
        )
        role_arn = resp["Role"]["Arn"]
        logger.info("Created agent role: %s", role_arn)
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = f"arn:aws:iam::{account_id}:role/{AGENT_ROLE_NAME}"
            logger.info("Agent role already exists: %s", role_arn)
        else:
            raise

    iam.put_role_policy(
        RoleName=AGENT_ROLE_NAME,
        PolicyName="BedrockAgentAccess",
        PolicyDocument=json.dumps(agent_policy),
    )

    logger.info("Waiting 10s for IAM propagation...")
    time.sleep(10)
    return role_arn


def main() -> None:
    session = boto3.Session(region_name=REGION)
    account_id = get_account_id(session)
    bedrock_agent = session.client("bedrock-agent")

    # Create agent role
    role_arn = create_agent_role(session, account_id)

    # Create agent
    logger.info("Creating Bedrock Agent '%s'...", AGENT_NAME)
    try:
        resp = bedrock_agent.create_agent(
            agentName=AGENT_NAME,
            agentResourceRoleArn=role_arn,
            foundationModel=SONNET_MODEL_ID,
            instruction=AGENT_INSTRUCTION,
            description="GraphRAG-based fraud analyst agent with graph traversal, risk scoring, and explainability",
            idleSessionTTLInSeconds=600,
            tags=TAGS,
        )
        agent_id = resp["agent"]["agentId"]
        logger.info("Created agent: %s (id=%s)", AGENT_NAME, agent_id)
    except ClientError as e:
        logger.error("Failed to create agent: %s", e)
        raise

    # Create action groups (requires Lambda ARNs — update these after deployment)
    lambda_prefix = f"arn:aws:lambda:{REGION}:{account_id}:function"

    action_groups = [
        {
            "name": "GraphQuery",
            "description": "Execute graph traversal queries on Neptune Analytics",
            "schema": GRAPH_QUERY_SCHEMA,
            "lambda_arn": f"{lambda_prefix}:graphrag-fraud-graph-query",
        },
        {
            "name": "RiskScore",
            "description": "Compute network-based risk scores for accounts",
            "schema": RISK_SCORE_SCHEMA,
            "lambda_arn": f"{lambda_prefix}:graphrag-fraud-risk-score",
        },
        {
            "name": "Explain",
            "description": "Generate human-readable fraud explanations with evidence chains",
            "schema": EXPLAIN_SCHEMA,
            "lambda_arn": f"{lambda_prefix}:graphrag-fraud-explain",
        },
    ]

    for ag in action_groups:
        try:
            bedrock_agent.create_agent_action_group(
                agentId=agent_id,
                agentVersion="DRAFT",
                actionGroupName=ag["name"],
                description=ag["description"],
                actionGroupExecutor={"lambda": ag["lambda_arn"]},
                apiSchema={"payload": json.dumps(ag["schema"])},
            )
            logger.info("Created action group: %s", ag["name"])
        except ClientError as e:
            logger.error("Failed to create action group %s: %s", ag["name"], e)

    # Associate Knowledge Base
    kb_id = os.environ.get("BEDROCK_KB_ID", "Z0ZI5NWJ4Z")
    logger.info("Associating Knowledge Base %s...", kb_id)
    try:
        bedrock_agent.associate_agent_knowledge_base(
            agentId=agent_id,
            agentVersion="DRAFT",
            knowledgeBaseId=kb_id,
            description="Financial transaction knowledge graph with customer, account, device, "
                        "merchant, and transaction data for fraud investigation.",
            knowledgeBaseState="ENABLED",
        )
        logger.info("Knowledge Base associated successfully")
    except ClientError as e:
        if "already associated" in str(e).lower() or "ConflictException" in str(e):
            logger.info("Knowledge Base already associated")
        else:
            logger.error("Failed to associate KB: %s", e)

    # Prepare agent
    logger.info("Preparing agent...")
    bedrock_agent.prepare_agent(agentId=agent_id)

    # Wait for preparation
    logger.info("Waiting for agent to be prepared...")
    for _ in range(30):
        time.sleep(5)
        agent_resp = bedrock_agent.get_agent(agentId=agent_id)
        status = agent_resp["agent"]["agentStatus"]
        logger.info("  Agent status: %s", status)
        if status == "PREPARED":
            break
        if status == "FAILED":
            logger.error("Agent preparation failed!")
            return

    # Create alias for invocation
    alias_name = "v1"
    try:
        alias_resp = bedrock_agent.create_agent_alias(
            agentId=agent_id,
            agentAliasName=alias_name,
            description="POC alias for fraud analyst agent",
            tags=TAGS,
        )
        alias_id = alias_resp["agentAlias"]["agentAliasId"]
        logger.info("Created alias '%s': %s", alias_name, alias_id)
    except ClientError as e:
        if "ConflictException" in str(e):
            # List aliases to find existing
            aliases = bedrock_agent.list_agent_aliases(agentId=agent_id)
            for a in aliases["agentAliasSummaries"]:
                if a["agentAliasName"] == alias_name:
                    alias_id = a["agentAliasId"]
                    logger.info("Alias '%s' already exists: %s", alias_name, alias_id)
                    break
        else:
            logger.error("Failed to create alias: %s", e)
            alias_id = "UNKNOWN"

    logger.info("")
    logger.info("=== SUMMARY ===")
    logger.info("Agent ID: %s", agent_id)
    logger.info("Agent Name: %s", AGENT_NAME)
    logger.info("Alias ID: %s", alias_id)
    logger.info("KB ID: %s", kb_id)
    logger.info("")
    logger.info("Test with:")
    logger.info('  python -c "import boto3; r=boto3.Session(region_name=\'us-east-1\').'
                'client(\'bedrock-agent-runtime\').invoke_agent(agentId=\'%s\','
                'agentAliasId=\'%s\',sessionId=\'test1\','
                'inputText=\'Investigate account A0009 for fraud\')"', agent_id, alias_id)


if __name__ == "__main__":
    main()
