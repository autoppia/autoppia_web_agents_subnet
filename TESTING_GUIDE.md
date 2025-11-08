# Testing Guide - New Reporting System

## ✅ **Integration Complete - Ready to Test**

**Branch:** `new-reports`  
**Commits:** 6 commits  
**Status:** ✅ All syntax checks pass

---

## 🎯 **What Was Integrated:**

### **Files Modified:**

1. **`neurons/validator.py`**
   - Added `ReportingMixin` to validator class

2. **`validator/round_start/mixin.py`**
   - Initialize `RoundReport` at round start
   - Record handshake sent and responses

3. **`validator/evaluation/mixin.py`**
   - Record task results with web_name, coldkey, success/failed

4. **`validator/settlement/mixin.py`**
   - Record consensus validators
   - Record consensus published (IPFS CID)
   - Record winner and weights
   - Finalize and send email at round end

5. **`validator/round_manager.py`**
   - Added `current_round_report` attribute

---

## 🚀 **How to Test:**

### **Step 1: Deploy to Server**

```bash
# On your local machine
cd ~/Escritorio/proyectos/autoppia/new_subnet/dashboard/autoppia_web_agents_subnet
git push origin new-reports

# On server
ssh contabo-iwap-dev
cd ~/autoppia_web_agents_subnet
git fetch origin
git checkout new-reports
git pull origin new-reports

# Restart validator
pm2 restart validator-wta
pm2 logs validator-wta
```

### **Step 2: Wait for Round to Complete**

The validator will automatically:
1. Collect all statistics during the round
2. Save pickle to `data/reports/rounds/round_N.pkl`
3. Send beautiful HTML email when round completes

### **Step 3: Check Your Email**

You should receive an email with:

#### **✅ Main Miner Table:**
```
#  UID  Hotkey      Coldkey     Tasks    Score%  AvgTime  AvgReward
🏆 1   80   5DUmbxsT... 5FHneW6u... 77/156   49.4%   12.34s   0.9234
   2   214  5FHneW6u... 5DUmbxsT... 65/156   41.7%   15.67s   0.8567
```

#### **✅ Per-Web Stats by Miner:**
```
Miner UID 80:
Web    Attempted  Success  Failed  Rate
web1   15         12       3       80.0%
web2   10         8        2       80.0%
...
```

#### **✅ Global Per-Web Summary:**
```
Web    Total Sent  Total Solved  Success Rate
web1   200         150           75.0%
web2   180         130           72.2%
...
```

#### **✅ Plus:**
- Handshake results (who responded)
- Winner highlighted
- Consensus validators (UID, hotkey, stake, IPFS CID)
- Top 5 miners
- Codex analysis (warnings/errors from logs)

---

## 🔍 **Verify Integration:**

### **Check logs for new messages:**

```bash
pm2 logs validator-wta | grep "📊 Round report"
```

You should see:
```
📊 Round report initialized for round N
📄 Round report saved to .../round_N.pkl
📧 Round report email sent for round N
```

### **Check pickle files:**

```bash
ls -lh ~/autoppia_web_agents_subnet/data/reports/rounds/
```

You should see: `round_N.pkl` files

### **Test resending old report:**

```bash
cd ~/autoppia_web_agents_subnet/scripts/validator/reporting
python3 resend_report.py 77
```

This should resend the email for round 77.

---

## 📊 **Data Flow:**

```
Round starts
   ↓
_init_round_report()
   → RoundReport created in memory
   ↓
Handshake
   ↓
_report_handshake_sent(256)
_report_handshake_response(uid=80, hotkey=..., agent_name=...)
   → Handshake data recorded
   ↓
Tasks (for each task, each miner)
   ↓
_report_task_result(
    uid=80,
    hotkey=...,
    coldkey=...,
    success=True,
    execution_time=12.34,
    eval_score=0.95,
    reward=0.95,
    web_name="web1"
)
   → Task stats recorded (per-miner, per-web, global)
   ↓
Consensus
   ↓
_report_consensus_validator(uid=83, hotkey=..., stake=30000, cid=...)
_report_consensus_published(cid=...)
_report_consensus_aggregated()
_report_set_final_scores({80: 0.9234, 214: 0.8567})
   → Consensus data recorded
   ↓
Winner
   ↓
_report_set_winner(uid=80)
_report_set_weights({80: 1.0, ...})
   → Winner and weights recorded
   ↓
Round ends
   ↓
_finalize_round_report(end_block=..., end_epoch=...)
   → Calculate averages
   → Save pickle: data/reports/rounds/round_N.pkl
   → Run Codex analysis on logs
   → Send HTML email (ALWAYS, even if errors)
   → Clear from memory
```

---

## ⚠️ **Important Notes:**

1. **Email ALWAYS sent** - Even if round had errors, you'll be notified
2. **Pickle persistent** - Can resend emails anytime
3. **Memory efficient** - Only current round in memory
4. **Codex optional** - If it times out, email still sends
5. **Per-web tracking** - See which webs are hardest/easiest

---

## 🧪 **Expected Behavior:**

After deploying:
- ✅ Round N starts → Log: "📊 Round report initialized"
- ✅ Handshake → Log: "✅ Handshake sent: 2/256"
- ✅ Tasks execute → Stats collected silently
- ✅ Round ends → Log: "📄 Round report saved" + "📧 Email sent"
- ✅ Email arrives with beautiful HTML tables

---

## 🔧 **Troubleshooting:**

### **No email received:**

```bash
# Check if report was saved
ls -lh ~/autoppia_web_agents_subnet/data/reports/rounds/

# Check validator logs for errors
pm2 logs validator-wta | grep -i "report\|email"

# Check email config
cat ~/.env | grep REPORT_MONITOR

# Try resending manually
python3 scripts/validator/reporting/resend_report.py <round_number>
```

### **Missing data in email:**

Check validator logs to see if all `_report_*()` methods were called:
- `📊 Round report initialized`
- Handshake responses recorded
- Task results recorded
- Consensus validators recorded
- Winner recorded

---

## ✅ **Ready to Deploy!**

All syntax checks pass. The system is ready for production testing.

**Deploy to server and wait for next round to complete (~14 minutes).**

