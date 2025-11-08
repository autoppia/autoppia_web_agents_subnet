# Integration Guide - New Reporting System

## 📋 **What Was Created:**

### **New Files:**

```
autoppia_web_agents_subnet/validator/reporting/
├── __init__.py           ← Package init
├── round_report.py       ← RoundReport, MinerReport, ConsensusValidatorReport classes
├── email_sender.py       ← HTML email generation and sending
└── mixin.py              ← ReportingMixin to integrate into validator
```

### **Modified Files:**

```
autoppia_web_agents_subnet/validator/
└── round_manager.py      ← Added current_round_report attribute
```

---

## 🎯 **How It Works:**

### **Architecture:**

```
1. Round starts
   → RoundReport created in memory (self.round_manager.current_round_report)

2. During round
   → Statistics collected via _report_*() methods

3. Round ends
   → Finalize report
   → Save to pickle: data/reports/rounds/round_N.pkl
   → Send email (ALWAYS, even if errors)
   → Clear from memory

4. Request old report
   → Load from pickle
   → Resend email
```

### **1. RoundReport Class**

Stores current round statistics in memory:

```python
report = RoundReport(
    round_number=77,
    validator_round_id="validator_round_77_...",
    validator_uid=101,
    validator_hotkey="5Dyp...",
    start_block=6837604,
    start_epoch=18993.34,
    planned_tasks=6,
)

# Add miners
report.record_handshake_response(uid=80, hotkey="5DUmb...", agent_name="Agent 80")
report.record_handshake_response(uid=214, hotkey="5FHne...", agent_name="Agent 214")

# Record task results
report.record_task_result(uid=80, success=True, execution_time=12.34, eval_score=0.95, reward=0.95)
report.record_task_result(uid=80, success=False, execution_time=15.67, eval_score=0.0, reward=0.0)

# Add consensus validators
report.add_consensus_validator(uid=83, hotkey="5FHne...", stake_tao=30000, ipfs_cid="Qm...")

# Finalize
report.finalize_round(end_block=6837676, end_epoch=18993.54)

# Send email
send_round_report_email(report, codex_analysis="...")
```

---

## 🔧 **Integration Points:**

### **Step 1: Add ReportingMixin to Validator**

In `neurons/validator.py`:

```python
from autoppia_web_agents_subnet.validator.reporting.mixin import ReportingMixin

class Validator(
    RoundStateValidatorMixin,
    RoundPhaseValidatorMixin,
    RoundStartMixin,
    EvaluationPhaseMixin,
    SettlementMixin,
    ValidatorPlatformMixin,
    ReportingMixin,  # ← ADD THIS
    BaseValidatorNeuron,
):
    pass
```

### **Step 2: Initialize Report at Round Start**

In `round_start/mixin.py`, after starting the round:

```python
# After self.round_manager.start_new_round(current_block)
self._init_round_report(
    round_number=round_number,
    validator_round_id=validator_round_id,
    start_block=start_block,
    start_epoch=start_epoch,
    planned_tasks=len(all_tasks),
)
```

### **Step 3: Record Handshake**

In `round_start/mixin.py`, after handshake:

```python
# Record total miners contacted
self._report_handshake_sent(total_miners=len(self.metagraph.axons))

# For each miner that responded
for uid in active_miner_uids:
    hotkey = self.metagraph.hotkeys[uid]
    payload = handshake_payloads.get(uid, {})
    agent_name = payload.get("agent_name")
    agent_image = payload.get("agent_image")

    self._report_handshake_response(uid, hotkey, agent_name, agent_image)
```

### **Step 4: Record Task Results**

In `evaluation/mixin.py`, after evaluating each task:

```python
for uid in active_miner_uids:
    hotkey = self.metagraph.hotkeys[uid]
    solution = solutions.get(uid)
    evaluation = evaluations.get(uid)

    success = evaluation.score > 0 if evaluation else False
    execution_time = execution_times.get(uid, 0.0)
    eval_score = evaluation.score if evaluation else 0.0
    reward = rewards.get(uid, 0.0)

    self._report_task_result(uid, hotkey, success, execution_time, eval_score, reward)
```

### **Step 5: Record Consensus**

In `settlement/consensus.py`, after aggregating consensus:

```python
# After fetching all validators' scores
for validator_info in validators_list:
    self._report_consensus_validator(
        uid=validator_info.get("uid"),
        hotkey=validator_info["hotkey"],
        stake_tao=validator_info["stake"],
        ipfs_cid=validator_info.get("cid"),
        miners_reported=len(validator_info.get("scores", {})),
        miner_scores=validator_info.get("scores"),
    )

# After publishing our own consensus
self._report_consensus_published(ipfs_cid=our_cid)

# After aggregating scores
self._report_consensus_aggregated()
self._report_set_final_scores(aggregated_scores)
```

### **Step 6: Record Winner and Weights**

In `settlement/mixin.py`, after calculating winner:

```python
# Set local winner (before consensus)
self._report_set_winner(winner_uid, is_local=True)

# Set final winner (after consensus)
self._report_set_winner(final_winner_uid, is_local=False)

# Set final weights
self._report_set_weights(final_weights_dict)
```

### **Step 7: Finalize and Send Email**

In `settlement/mixin.py`, at the end of the round:

```python
# After finish_round_flow
self._finalize_round_report(
    end_block=current_block,
    end_epoch=current_epoch,
)

# This will:
# 1. Calculate all averages
# 2. Rank miners
# 3. Save JSON to data/round_reports/round_N.json
# 4. Run Codex analysis on logs
# 5. Send beautiful HTML email
```

---

## 📧 **Email Will Contain:**

- ✅ Round overview (blocks, epochs, duration)
- ✅ Handshake results (who responded)
- ✅ Complete miner table (UID, hotkey, tasks success/failed, avg time, avg reward)
- ✅ Winner with score
- ✅ Consensus validators (UID, hotkey, stake, IPFS CID)
- ✅ Top 5 miners
- ✅ Codex AI analysis of logs (warnings/errors)

---

## 🔍 **Benefits:**

1. **No log parsing** - All data in memory
2. **Complete data** - Nothing is missing
3. **Fast** - No need to scan logs
4. **Reliable** - Not dependent on log format
5. **Beautiful HTML emails** - Professional formatting
6. **Codex only for logs** - Analyzes warnings/errors, not extracting data

---

## 📝 **Next Steps:**

1. Integrate `ReportingMixin` into validator class
2. Add `_init_round_report()` call at round start
3. Add `_report_handshake_*()` calls after handshake
4. Add `_report_task_result()` calls after each task
5. Add `_report_consensus_*()` calls during consensus
6. Add `_finalize_round_report()` call at round end

---

## 🧪 **Testing:**

After integration, the validator will automatically:

- Collect all statistics during the round
- Send a beautiful HTML email when the round completes
- Save JSON report to `data/round_reports/round_N.json`

No need to parse logs or run external scripts!

---

**This is the CORRECT approach** ✅

---

## 📧 **Requesting Past Round Reports:**

### **From Python:**

```python
from autoppia_web_agents_subnet.validator.reporting.mixin import ReportingMixin

# Load round report
report = ReportingMixin.load_round_report(77)

if report:
    print(f"Round {report.round_number}")
    print(f"Winner: UID {report.final_winner_uid}")
    print(f"Miners: {len(report.miners)}")

# Resend email for round 77
ReportingMixin.resend_round_report(77)
```

### **From Command Line:**

```bash
cd ~/autoppia_web_agents_subnet/scripts/validator/reporting

# Resend report for round 77
python3 resend_report.py 77
```

This will:
1. Load `data/reports/rounds/round_77.pkl`
2. Run Codex analysis on `logs/rounds/round_77.log`
3. Send beautiful HTML email

---

## 💾 **Data Storage:**

```
data/reports/rounds/
├── round_77.pkl    ← Complete RoundReport object
├── round_78.pkl
└── round_79.pkl
```

**Benefits:**
- ✅ Fast retrieval (no log parsing)
- ✅ Complete data (all statistics)
- ✅ Can resend emails anytime
- ✅ Persistent (survives validator restarts)

---

**This is the CORRECT approach** ✅
