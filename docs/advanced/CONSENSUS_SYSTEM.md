# Distributed Consensus System

## Overview

The Autoppia subnet implements a **distributed consensus mechanism** that allows multiple validators to collaborate on determining miner scores. Instead of each validator independently deciding winners (which can lead to divergence and VTrust penalties), validators share their evaluation results via **IPFS** and **blockchain commitments**, then compute a **stake-weighted average** to reach consensus.

## Table of Contents

- [How It Works](#how-it-works)
- [Round Timeline](#round-timeline)
- [IPFS Architecture](#ipfs-architecture)
- [Configuration](#configuration)
- [Testing Mode vs Production](#testing-mode-vs-production)
- [Troubleshooting](#troubleshooting)

---

## How It Works

### The Problem

Each validator runs the same code but generates **different tasks** for miners. This can lead to divergent results:

```
Validator A: Miner 107 wins (score 0.92)
Validator B: Miner 59 wins (score 0.91)
Validator C: Miner 107 wins (score 0.93)

Problem: Validators disagree on who won
Result: VTrust penalties for Validator B
```

### The Solution: Stake-Weighted Consensus

All validators share their scores via IPFS and blockchain, then compute a weighted average:

```
Validator A (700k τ stake): Miner 107 → 0.92
Validator B (100k τ stake): Miner 107 → 0.88
Validator C (100k τ stake): Miner 107 → 0.93

Consensus score = (0.92 × 700k + 0.88 × 100k + 0.93 × 100k) / 900k
                = 0.915

Result: ALL validators converge on the same winner (Miner 107)
```

---

## Round Timeline

### Testing Mode (14.4 minute rounds)

```
0%──────────50%───────────75%────────────100%
│           │            │             │
│   TASK    │  PUBLISH   │   FETCH     │  WEIGHTS
│   EVAL    │  TO IPFS   │  FROM IPFS  │  ON-CHAIN
│           │            │             │
0 min      7.2 min      10.8 min      14.4 min

Phase 1 (0-50%): Task Evaluation
  - Generate tasks
  - Send to miners
  - Evaluate responses
  - Calculate local scores

Phase 2 (50%): IPFS Publish
  - Upload scores to IPFS → get CID
  - Commit CID to blockchain
  - Gap: 3.6 min (18 blocks) for propagation

Phase 3 (75%): IPFS Aggregation
  - Read commitments from blockchain
  - Download all validators' payloads from IPFS
  - Compute stake-weighted average
  - Cache aggregated scores

Phase 4 (100%): Set Weights
  - Apply Winner-Takes-All (WTA)
  - Commit weights to blockchain
```

### Production Mode (4.8 hour rounds)

```
0%──────────────────75%───────────87.5%───────100%
│                   │           │          │
│   TASK EVAL       │  PUBLISH  │  FETCH   │  WEIGHTS
│                   │           │          │
0h                 3.6h        4.2h       4.8h

Phase 1 (0-75%): Task Evaluation (3.6 hours)
  - Generate 75 tasks
  - Distribute to miners
  - Evaluate all responses

Phase 2 (75%): IPFS Publish
  - Upload scores to IPFS
  - Commit CID to blockchain
  - Gap: 36 minutes (180 blocks) for propagation

Phase 3 (87.5%): IPFS Aggregation
  - Aggregate scores from all validators

Phase 4 (100%): Set Weights
  - Apply WTA and commit to chain
```

---

## IPFS Architecture

### What is IPFS?

**IPFS (InterPlanetary File System)** is a decentralized storage network where files are identified by their content hash (CID), not location.

### Why IPFS + Blockchain?

**Blockchain alone:**

- ❌ Too expensive to store large JSON payloads
- ❌ Limited storage capacity

**IPFS alone:**

- ❌ No guarantee of data availability
- ❌ No cryptographic proof of authorship

**IPFS + Blockchain (our approach):**

- ✅ Store large payloads in IPFS (cheap, scalable)
- ✅ Store only CID on blockchain (small, ~50 bytes)
- ✅ Validators sign commitments with their hotkey (verifiable)
- ✅ Anyone can verify and audit the data

---

## IPFS Publishing Flow

### Step 1: Validator A publishes scores (at 50%/75% of round)

```python
# 1. Build payload
payload = {
    "v": 1,
    "round_number": 69,
    "validator_hotkey": "5DUmbxsT...",
    "validator_uid": 195,
    "tasks_completed": 5,
    "scores": {
        "59": 0.45,
        "107": 0.92,
        "145": 0.33
    }
}

# 2. Upload to IPFS
POST http://ipfs.metahash73.com:5001/api/v0/add
Body: {payload as JSON}

# 3. IPFS calculates content hash
CID = "QmXyZ123abc456..."  # Unique for this exact content

# 4. Commit CID to blockchain
Blockchain[netuid=36][commitments]["5DUmbxsT..."] = {
    "v": 4,
    "e": 18673,  # epoch_start - 1
    "pe": 18674, # epoch_end
    "c": "QmXyZ123abc...",  # The CID
    "r": 69
}
```

**Logs you'll see:**

```
📤 CONSENSUS PUBLISH | round=69 es=18673.0 et=18674.0 tasks=5 agents=2
🌐 IPFS UPLOAD | api_url=http://ipfs.metahash73.com:5001/api/v0
✅ IPFS UPLOAD SUCCESS | cid=QmXyZ123abc... | size=2048 bytes
📬 CONSENSUS COMMIT | e=18673→pe=18674 r=69 cid=QmXyZ123abc...
```

---

## IPFS Aggregation Flow

### Step 2: Validator B aggregates scores (at 75%/87.5% of round)

```python
# 1. Read all commitments from blockchain
GET Blockchain[netuid=36][commitments]

Response: {
    "5DUmbxsT...": {"c": "QmXyZ123...", "e": 18673, "pe": 18674},
    "5CxVMzwR...": {"c": "QmAbc987...", "e": 18673, "pe": 18674}
}

# 2. Filter by epoch window (only same round)
expected_e = 18673
expected_pe = 18674

# 3. For each valid commitment, download from IPFS
GET http://ipfs.metahash73.com:5001/api/v0/cat?arg=QmXyZ123...
→ {"scores": {"59": 0.45, "107": 0.92, ...}}

GET http://ipfs.metahash73.com:5001/api/v0/cat?arg=QmAbc987...
→ {"scores": {"59": 0.50, "107": 0.88, ...}}

# 4. Get stake for each validator
Validator A stake = 700k τ
Validator B stake = 100k τ

# 5. Compute stake-weighted average
For miner 107:
    weighted_sum = (0.92 × 700k) + (0.88 × 100k) = 732k
    weight_total = 700k + 100k = 800k
    consensus_score = 732k / 800k = 0.915

# 6. Apply WTA (Winner-Takes-All)
winner = miner with highest consensus_score
winner_weight = 1.0
all_others = 0.0

# 7. Set weights on-chain
All validators set the SAME weights → consensus achieved ✅
```

**Logs you'll see:**

```
🔎 CONSENSUS AGGREGATE | expected e=18673 pe=18674 | commits_seen=2
📋 Found commitments from 2 validators
🎯 Filtering for: e=18673 pe=18674
🌐 IPFS DOWNLOAD | validator=5DUmbxsT… | cid=QmXyZ123...
✅ IPFS DOWNLOAD SUCCESS | cid=QmXyZ123... | scores=64 miners
🌐 IPFS DOWNLOAD | validator=5CxVMzwR… | cid=QmAbc987...
✅ IPFS DOWNLOAD SUCCESS | cid=QmAbc987... | scores=64 miners
🤝 CONSENSUS INCLUDED | validators=2 | miners=64
📊 Skip summary — wrong_epoch=0 missing_cid=0 low_stake=0 ipfs_fail=0
🤝 Using aggregated scores from commitments (64 miners)
```

---

## Configuration

### Core Settings

```python
# Enable/disable distributed consensus
ENABLE_DISTRIBUTED_CONSENSUS = true  # Default: enabled

# When to stop task evaluation and upload to IPFS (absolute % of round)
STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION = 0.90  # Production: 90%

# When to fetch IPFS payloads and calculate consensus weights (absolute % of round)
FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION = 0.95  # Production: 95%

# Minimum stake to be included in consensus calculations
MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 10000.0  # 10k τ minimum
```

### Environment Variables (.env)

```bash
# Enable consensus (default: true)
ENABLE_DISTRIBUTED_CONSENSUS=true

# IPFS node endpoint
IPFS_API_URL=http://ipfs.metahash73.com:5001/api/v0

# Stake requirements (can override defaults)
MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO=10000

# Testing mode (changes all timing defaults)
TESTING=true
```

---

## Testing Mode vs Production

| Setting             | Testing               | Production           | Reason                                       |
| ------------------- | --------------------- | -------------------- | -------------------------------------------- |
| **Round Duration**  | 0.2 epochs (14.4 min) | 4 epochs (4.8 hours) | Fast iteration vs thorough evaluation        |
| **Tasks**           | 5 tasks               | 75 tasks             | Speed vs completeness                        |
| **Stop Task Eval**  | 50% (7.2 min)         | 75% (3.6h)           | More time for consensus in testing           |
| **Fetch IPFS**      | 75% (10.8 min)        | 87.5% (4.2h)         | Same gap ratio maintained                    |
| **Propagation Gap** | 25% (18 blocks)       | 12.5% (180 blocks)   | Both sufficient for blockchain propagation   |
| **Late Start Skip** | 95% (permissive)      | 30% (conservative)   | Allow restarts in testing                    |
| **Min Stake**       | 0 τ (anyone)          | 10,000 τ (vetted)    | Testing accessibility vs production security |
| **Crash Recovery**  | Enabled               | Enabled              | Resume mid-round after restart               |

---

## Stake Requirements

### MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO

**What it controls:** Which validators are **included** when computing consensus scores.

**Example:**

```
Validator A: 50k τ stake → scores {"107": 0.92}
Validator B: 5k τ stake → scores {"107": 0.88}
MIN_STAKE = 10k τ

Aggregation:
  ✅ Validator A: INCLUDED (50k > 10k)
  ❌ Validator B: EXCLUDED (5k < 10k)

Consensus score[107] = 0.92 (only Validator A counts)
```

**Why this design?**

- ✅ **Anyone can publish** to IPFS (transparency, auditability)
- ✅ **Only high-stake validators count** in consensus (sybil resistance)
- ✅ **Low-stake validators** still benefit (use aggregated scores from others)

---

## Late Start Protection

### SKIP_ROUND_IF_STARTED_AFTER_FRACTION

**What it does:** Prevents starting a round too late to meaningfully participate.

**Testing:** 0.95 (skip only if >95% complete)

- Allows almost any restart
- Useful for rapid development iterations

**Production:** 0.30 (skip if >30% complete)

- Conservative approach
- Ensures sufficient time for full round participation

**Example:**

```
Round 50% complete when validator starts:

Testing (threshold=95%):
  50% < 95% → ✅ START (has 50% time remaining)

Production (threshold=30%):
  50% > 30% → ⏭️ SKIP (wait for next round)
```

---

## Troubleshooting

### Issue: `validators=0` (no aggregated scores)

**Symptoms:**

```
🔎 CONSENSUS AGGREGATE | commits_seen=2
🤝 CONSENSUS INCLUDED | validators=0 (no aggregated scores)
```

**Diagnosis:** Check the skip summary:

```
📊 Why no validators? — wrong_epoch=2 missing_cid=0 low_stake=0 ipfs_fail=0
```

**Common causes:**

1. **wrong_epoch > 0**

   - Validators are in different epoch windows
   - Solution: Ensure all validators start at same epoch boundary

2. **missing_cid > 0**
   - Validators didn't publish to IPFS
   - Check: `grep "CONSENSUS PUBLISH" logs`
3. **low_stake > 0**

   - Validators have insufficient stake
   - Solution: Set `MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO=0` for testing

4. **ipfs_fail > 0**
   - IPFS downloads failed
   - Check IPFS node accessibility: `curl http://ipfs.metahash73.com:5001/api/v0/id`

---

### Issue: IPFS upload fails

**Symptoms:**

```
❌ IPFS UPLOAD FAILED | error=ConnectionError: Connection refused
```

**Solution:**

```bash
# Test IPFS node manually
curl "http://ipfs.metahash73.com:5001/api/v0/id"

# If fails, use alternative node
export IPFS_API_URL=https://ipfs.infura.io:5001
```

---

### Issue: miners=0 despite validators=2

**Symptoms:**

```
🤝 CONSENSUS INCLUDED | validators=2 | miners=0
```

**Explanation:** This means:

- ✅ Successfully aggregated scores from 2 validators
- ❌ BUT all miners have score ≤ 0.0 after aggregation

**Why?** Miners failed their tasks (e.g., missing seeds, wrong actions).

**This is NORMAL** when:

- Testing with broken miners
- All miners fail validation
- Seeds are mismatched

**Not a consensus bug** - the aggregation worked correctly, there just weren't any positive scores to aggregate.

---

### Issue: "Fresh start late in round" keeps appearing

**Symptoms:**

```
⏭️ Fresh start late in round: 72.2% >= 30% — skipping to next round
Waiting ~5.8m to next boundary...
```

**Cause:** Validator keeps restarting mid-round.

**Solutions:**

1. **Increase threshold** (testing):

   ```bash
   SKIP_ROUND_IF_STARTED_AFTER_FRACTION=0.95
   ```

2. **Avoid restarts mid-round**: keep the validator stable during the current round (or let it wait for next boundary).

3. **Start at epoch boundary:**
   - Wait for epoch to be exact multiple of ROUND_SIZE_EPOCHS
   - Example: 18674.00, 18674.20, 18674.40, 18674.60, 18674.80

---

## Verifying IPFS Data

### Manual CID Verification

```bash
# 1. Get CID from logs
CID=$(pm2 logs validator | grep "CONSENSUS COMMIT" | tail -1 | grep -oP 'cid=\K[^ ]+')

# 2. Download from IPFS
curl "http://ipfs.metahash73.com:5001/api/v0/cat?arg=$CID" | jq .

# Expected output:
{
  "v": 1,
  "round_number": 69,
  "validator_hotkey": "5DUmbxsT...",
  "validator_uid": 195,
  "scores": {
    "59": 0.45,
    "107": 0.92
  }
}
```

### Via Public Gateways

```bash
# Option 1: ipfs.io
curl "https://ipfs.io/ipfs/$CID" | jq .

# Option 2: Cloudflare
curl "https://cloudflare-ipfs.com/ipfs/$CID" | jq .

# Option 3: Browser
https://ipfs.io/ipfs/$CID
```

---

## Security Considerations

### Stake-Weighted Voting

- Validators with more stake have more influence
- Prevents sybil attacks (can't just spin up 100 low-stake validators)
- 10k τ minimum ensures serious participants only

### Content Integrity

- IPFS CIDs are cryptographic hashes
- Impossible to modify content without changing CID
- Blockchain commitments are signed with validator hotkey
- Anyone can verify authenticity

### No Central Point of Failure

- IPFS is distributed across multiple nodes
- No single server can censor or modify data
- Blockchain ensures permanent record of commitments

---

## Configuration Reference

### Testing Configuration

```python
TESTING = true

# Round Structure
ROUND_SIZE_EPOCHS = 0.2                              # 14.4 minutes
TASKS_PER_SEASON = 5                                 # 5 tasks per season
DZ_STARTING_BLOCK = 6870000

# Phase Timing (absolute % of round)
STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION = 0.65  # Stop evaluation and upload IPFS at 65%
FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION = 0.75  # Fetch and calculate weights at 75%

# Checkpoint System & Late Start
ENABLE_CHECKPOINT_SYSTEM = True
SKIP_ROUND_IF_STARTED_AFTER_FRACTION = 0.95          # Very permissive

# Consensus
MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 0.0          # No stake required
```

### Production Configuration

```python
TESTING = false

# Round Structure
ROUND_SIZE_EPOCHS = 4.0                              # 4.8 hours (changed from 20.0)
TASKS_PER_SEASON = 75                                # 75 tasks per season
DZ_STARTING_BLOCK = 6870000

# Phase Timing (absolute % of round)
STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION = 0.90  # Stop evaluation and upload IPFS at 90%
FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION = 0.95  # Fetch and calculate weights at 95%

# Checkpoint System & Late Start
ENABLE_CHECKPOINT_SYSTEM = True
SKIP_ROUND_IF_STARTED_AFTER_FRACTION = 0.30          # Conservative

# Consensus
MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 10000.0      # 10k τ minimum
```

---

## Key Design Decisions

### 1. Why absolute timing instead of relative?

**Before (confusing):**

```python
STOP_TASK = 75% (absolute)
FETCH = 50% of settlement (relative)
→ Actual fetch time = 75% + (25% × 50%) = 87.5% 🤔
```

**After (clear):**

```python
STOP_TASK = 75% (absolute)
FETCH = 87.5% (absolute)
→ Actual fetch time = 87.5% ✅
```

### 2. Why no MIN_STAKE_TO_PUBLISH (removed)?

**Before:** Two separate stake filters

- MIN_STAKE_TO_PUBLISH: Filter who can publish to IPFS
- MIN_STAKE_TO_AGGREGATE: Filter who is included in consensus

**After:** Only one filter (MIN_TO_AGGREGATE)

**Reason:**

- Anyone can publish to IPFS (transparency, auditability)
- Only high-stake validators count in consensus (sybil resistance)
- Low-stake validators still benefit from consensus (follow the leaders)

### 3. Why remove IPFS_PROPAGATION_WAIT_BLOCKS?

**Before:** Hardcoded 10-block wait after commit

**After:** Natural gap is sufficient

**Analysis:**

- Testing gap: 25% of 72 blocks = **18 blocks** (sufficient for propagation)
- Production gap: 12.5% of 1440 blocks = **180 blocks** (sufficient for propagation)
- Redundant safety check removed for simplicity

---

## Example: Full Round Flow

### Scenario: 2 validators testing with 1 miner

```
Minute 0:00 - Both validators start
  Validator A (UID 195): Generates tasks
  Validator B (UID 20): Generates tasks

Minute 1:00 - Task dispatch
  Both: Send tasks to Miner 59

Minute 2:00 - Evaluation
  Validator A: Miner 59 score = 0.45
  Validator B: Miner 59 score = 0.50
  (Slight difference due to different tasks)

Minute 7:20 - IPFS Publish (50% of round)
  Validator A:
    → Upload {"scores": {"59": 0.45}} to IPFS
    → Get CID: QmXyZ123...
    → Commit CID to blockchain

  Validator B:
    → Upload {"scores": {"59": 0.50}} to IPFS
    → Get CID: QmAbc987...
    → Commit CID to blockchain

Minute 10:48 - IPFS Aggregation (75% of round)
  Both validators:
    → Read blockchain commitments (see 2 CIDs)
    → Download both payloads from IPFS
    → Compute weighted average:
      score[59] = (0.45 × stake_A + 0.50 × stake_B) / (stake_A + stake_B)
    → Apply WTA
    → Cache result

Minute 14:24 - Set Weights (100% of round)
  Both validators:
    → Use cached aggregated scores
    → Apply WTA: winner = Miner 59, weight = 1.0
    → Commit weights to blockchain
    ✅ BOTH commit the SAME weights (consensus achieved!)
```

---

## Monitoring Commands

### Check if consensus is active

```bash
pm2 logs validator | grep "Distributed consensus"
# Should show: "Distributed consensus active: true"
```

### Monitor IPFS publish

```bash
pm2 logs validator | grep "IPFS UPLOAD"
# Expected at 50% (testing) or 75% (production)
```

### Monitor IPFS aggregation

```bash
pm2 logs validator | grep "CONSENSUS INCLUDED"
# Should show validators=N where N > 0
```

### Check for consensus convergence

```bash
# See if using aggregated scores
pm2 logs validator | grep "Using aggregated scores"

# Verify winner
pm2 logs validator | grep "Winner uid"
```

### Debug why validators=0

```bash
pm2 logs validator --lines 100 | grep "Skip\|wrong_epoch\|ipfs_fail"
```

---

## FAQ

### Q: Can I disable consensus temporarily?

**A:** Yes, set in `.env`:

```bash
ENABLE_DISTRIBUTED_CONSENSUS=false
```

Each validator will then work independently (no IPFS sharing).

### Q: What happens if IPFS node is down?

**A:** Validator will:

1. Try to publish → fail gracefully
2. Fall back to local scores only
3. Log warning but continue functioning

### Q: Do all validators need the same IPFS node?

**A:** No. IPFS is a distributed network. Once published to any node, content propagates to all nodes. Any validator can retrieve it from any IPFS node or gateway.

### Q: What if validators are in different epoch windows?

**A:** They won't aggregate each other's scores. Consensus only works when validators are synchronized to the same round boundaries (multiples of ROUND_SIZE_EPOCHS).

### Q: Can validators see each other's scores before setting weights?

**A:** Yes, that's the point! At 75%/87.5% of the round, all validators download and aggregate each other's scores before setting weights. This ensures convergence.

---

## Additional Resources

- [IPFS Documentation](https://docs.ipfs.tech/)
- [Bittensor Commit-Reveal](https://docs.bittensor.com/)
- [Round System Documentation](./round_system.md)

---
