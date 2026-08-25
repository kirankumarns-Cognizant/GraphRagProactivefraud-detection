-- GraphRAG Fraud Detection POC — Sample openCypher Queries
-- Run these in Neptune Graph Explorer or via the Neptune API

-- 1. Count all node types
MATCH (n) RETURN labels(n) AS type, count(n) AS count ORDER BY count DESC

-- 2. Count all edge types
MATCH ()-[r]->() RETURN type(r) AS relationship, count(r) AS count ORDER BY count DESC

-- 3. Find accounts sharing devices (fraud ring indicator)
MATCH (a1:Account)-[:LOGGED_IN_FROM]->(d:Device)<-[:LOGGED_IN_FROM]-(a2:Account)
WHERE a1 <> a2
RETURN a1.account_id, a2.account_id, d.device_id

-- 4. Multi-hop: Find all entities within 3 hops of a specific account
MATCH path = (start:Account {account_id: 'A0001'})-[*1..3]-(connected)
RETURN path

-- 5. Find fraud rings via shared devices (community detection seed)
MATCH (a1:Account)-[:SHARED_DEVICE]-(a2:Account)
RETURN a1.account_id, a2.account_id

-- 6. Detect velocity bursts: accounts with >10 txns in 1 hour
MATCH (a:Account)<-[:INITIATED_BY]-(t:Transaction)
WITH a, t, datetime(t.timestamp) AS ts
WITH a, ts, count(t) AS txn_count
WHERE txn_count > 10
RETURN a.account_id, txn_count ORDER BY txn_count DESC

-- 7. Card testing pattern: failed then successful txns to same merchant
MATCH (a:Account)<-[:INITIATED_BY]-(t1:Transaction)-[:PURCHASED_AT]->(m:Merchant),
      (a)<-[:INITIATED_BY]-(t2:Transaction)-[:PURCHASED_AT]->(m)
WHERE t1.status = 'failed' AND t2.status = 'completed'
  AND datetime(t2.timestamp) > datetime(t1.timestamp)
RETURN a.account_id, m.merchant_id, t1.transaction_id, t2.transaction_id

-- 8. Impossible travel: same account, same day, distant locations
MATCH (a:Account)<-[:INITIATED_BY]-(t1:Transaction),
      (a)<-[:INITIATED_BY]-(t2:Transaction)
WHERE t1 <> t2
  AND t1.country <> t2.country
  AND date(datetime(t1.timestamp)) = date(datetime(t2.timestamp))
RETURN a.account_id, t1.location, t2.location, t1.timestamp, t2.timestamp

-- 9. Customer-to-merchant path (for explainability)
MATCH path = shortestPath(
  (c:Customer {customer_id: 'C0001'})-[*]-(m:Merchant {merchant_id: 'M0001'})
)
RETURN path

-- 10. High PageRank devices (most connected)
-- Note: Run PageRank algorithm first in Neptune Analytics, then query:
-- CALL neptune.algo.pageRank({}) YIELD node, score
-- RETURN node, score ORDER BY score DESC LIMIT 10
