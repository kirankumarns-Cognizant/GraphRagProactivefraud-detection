#!/usr/bin/env python3
"""Diagnose Neptune graph creation failure."""

import boto3
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGION = "us-east-1"
GRAPH_ID = "g-eu4wyikdt8"

def diagnose():
    """Check graph status and import task details."""
    neptune = boto3.client("neptune-graph", region_name=REGION)
    
    # Get graph details
    try:
        graph = neptune.get_graph(graphIdentifier=GRAPH_ID)
        logger.info("Graph Status: %s", graph.get("status"))
        logger.info("Graph Name: %s", graph.get("name"))
        logger.info("Graph ID: %s", graph.get("id"))
    except Exception as e:
        logger.error("Failed to get graph: %s", e)
        return
    
    # Get import tasks (without graphIdentifier)
    try:
        tasks = neptune.list_import_tasks()
        import_tasks = tasks.get("importTasks", [])
        
        if not import_tasks:
            logger.warning("No import tasks found")
            return
        
        # Filter for our graph
        for task in import_tasks:
            if task.get("graphId") == GRAPH_ID or task.get("graphIdentifier") == GRAPH_ID:
                logger.info("\nImport Task Details:")
                logger.info("  Task ID: %s", task.get("taskId"))
                logger.info("  Status: %s", task.get("status"))
                logger.info("  Source: %s", task.get("source"))
                logger.info("  Format: %s", task.get("format"))
                
                if task.get("status") == "FAILED":
                    logger.error("  Failure Details: %s", task.get("failureDetails", "Unknown"))
                
                stats = task.get("importTaskStatistics", {})
                logger.info("  Nodes Processed: %s", stats.get("totalNodes", 0))
                logger.info("  Edges Processed: %s", stats.get("totalEdges", 0))
                logger.info("  Parse Errors: %s", stats.get("parseErrors", 0))
                logger.info("  Type Errors: %s", stats.get("typeErrors", 0))
                break
        else:
            logger.warning("No import task found for graph %s", GRAPH_ID)
            logger.info("Available import tasks:")
            for task in import_tasks[:5]:
                logger.info("  - %s (graph: %s)", task.get("taskId"), task.get("graphId", "unknown"))
            
    except Exception as e:
        logger.error("Failed to get import tasks: %s", e)

if __name__ == "__main__":
    diagnose()