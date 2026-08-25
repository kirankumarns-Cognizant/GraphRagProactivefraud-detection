# Data Profile — GraphRAG Fraud Detection POC

## Entity Counts
| Entity | Count |
|--------|-------|
| Customers | 100 |
| Accounts | 150 |
| Devices | 50 |
| Merchants | 30 |
| IP Addresses | 20 |
| Transactions | 1364 |
| Relationships | 3347 |

## Fraud Summary
| Metric | Value |
|--------|-------|
| Fraud rings | 5 |
| Fraud customers | 21 |
| Fraud accounts | 30 |
| Fraud transactions | 404 (29.6%) |
| Total fraud amount (AUD) | 2,427,755.66 |
| Temporal anomalies | 12 |
| Geographic anomalies | 3 |

## Fraud Patterns Embedded
- off_hours
- velocity_abuse
- impossible_travel
- card_testing
- shared_device
- velocity_burst
- merchant_collusion
- identity_layering
- ip_rotation

## Transaction Amount Distribution
- Min: 0.20
- P25: 20.47
- Median: 62.39
- Mean: 1825.90
- P75: 401.39
- P95: 9446.49
- Max: 48833.16

## Transactions per Account
- Min: 1
- Median: 7
- Max: 24
- Accounts with 0 txns: 0

## Fraud Ring Details

### RING-1: Device Sharing Ring
- Pattern: shared_device
- Members: 5 customers, 9 accounts
- Shared devices: D0007, D0048
- Shared IPs: N/A

### RING-2: IP Rotation Ring
- Pattern: ip_rotation
- Members: 3 customers, 3 accounts
- Shared devices: D0034, D0043
- Shared IPs: IP0009, IP0004

### RING-3: Merchant Collusion Ring
- Pattern: merchant_collusion
- Members: 4 customers, 6 accounts
- Shared devices: D0028
- Shared IPs: N/A

### RING-4: Velocity Abuse Ring
- Pattern: velocity_abuse
- Members: 5 customers, 6 accounts
- Shared devices: D0013, D0012
- Shared IPs: N/A

### RING-5: Identity Layering Ring
- Pattern: identity_layering
- Members: 4 customers, 6 accounts
- Shared devices: D0022
- Shared IPs: N/A
