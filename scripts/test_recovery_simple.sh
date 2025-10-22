#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Simple Recovery Test - Just shows you what to look for
# ═══════════════════════════════════════════════════════════════════════════════
# Usage: bash scripts/test_recovery_simple.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║         SIMPLE RECOVERY TEST - MANUAL VERIFICATION            ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

VALIDATOR_PROCESS="validator_6am"
CHECKPOINT_DIR="/data/validator_state/round_state"

# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: Check validator is running
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${BLUE}📋 Step 1: Checking validator status...${NC}"
if pm2 describe "$VALIDATOR_PROCESS" > /dev/null 2>&1; then
    STATUS=$(pm2 describe "$VALIDATOR_PROCESS" | grep "status" | awk '{print $4}')
    if [ "$STATUS" = "online" ]; then
        echo -e "${GREEN}✅ Validator is running${NC}"
    else
        echo -e "${RED}❌ Validator is not online (status: $STATUS)${NC}"
        echo -e "${YELLOW}   Run: pm2 restart $VALIDATOR_PROCESS${NC}"
        exit 1
    fi
else
    echo -e "${RED}❌ Validator process not found${NC}"
    exit 1
fi
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# Step 2: Check if checkpoint exists
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${BLUE}📋 Step 2: Checking for checkpoint...${NC}"
if [ -d "$CHECKPOINT_DIR" ]; then
    CHECKPOINT_FILES=$(ls -1 "$CHECKPOINT_DIR"/*.pkl 2>/dev/null | wc -l)
    if [ "$CHECKPOINT_FILES" -gt 0 ]; then
        echo -e "${GREEN}✅ Found checkpoint(s):${NC}"
        ls -lh "$CHECKPOINT_DIR"/*.pkl
        CHECKPOINT_FILE=$(ls -1 "$CHECKPOINT_DIR"/*.pkl | head -1)
        echo ""
        echo -e "${CYAN}📊 Checkpoint info:${NC}"
        echo -e "   Path: $CHECKPOINT_FILE"
        SIZE=$(du -h "$CHECKPOINT_FILE" | cut -f1)
        echo -e "   Size: $SIZE"
        MODIFIED=$(stat -c %y "$CHECKPOINT_FILE" 2>/dev/null || stat -f "%Sm" "$CHECKPOINT_FILE")
        echo -e "   Modified: $MODIFIED"
    else
        echo -e "${YELLOW}⚠️  No checkpoint found yet${NC}"
        echo -e "${YELLOW}   Wait for at least 1 task to complete (~5 minutes)${NC}"
        echo -e "${YELLOW}   Then run this script again${NC}"
        exit 0
    fi
else
    echo -e "${RED}❌ Checkpoint directory doesn't exist: $CHECKPOINT_DIR${NC}"
    echo -e "${YELLOW}   Creating directory...${NC}"
    mkdir -p "$CHECKPOINT_DIR"
    chmod 755 "$CHECKPOINT_DIR"
    echo -e "${GREEN}✅ Directory created${NC}"
    echo -e "${YELLOW}   Wait for at least 1 task to complete, then run this script again${NC}"
    exit 0
fi
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# Step 3: Show current validator logs
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${BLUE}📋 Step 3: Recent validator activity...${NC}"
echo -e "${CYAN}Last 10 log lines:${NC}"
pm2 logs "$VALIDATOR_PROCESS" --lines 10 --nostream
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# Step 4: Instructions for manual test
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                    MANUAL TEST INSTRUCTIONS                    ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Now you can test the recovery manually:${NC}"
echo ""
echo -e "${GREEN}1. Stop the validator:${NC}"
echo -e "   ${CYAN}pm2 stop $VALIDATOR_PROCESS${NC}"
echo ""
echo -e "${GREEN}2. Verify checkpoint still exists:${NC}"
echo -e "   ${CYAN}ls -lh $CHECKPOINT_DIR/${NC}"
echo ""
echo -e "${GREEN}3. Restart the validator:${NC}"
echo -e "   ${CYAN}pm2 restart $VALIDATOR_PROCESS${NC}"
echo ""
echo -e "${GREEN}4. Watch the recovery logs (look for these):${NC}"
echo -e "   ${CYAN}pm2 logs $VALIDATOR_PROCESS --lines 50${NC}"
echo ""
echo -e "${BLUE}Expected recovery logs:${NC}"
echo -e "   ${GREEN}♻️ Checkpoint loaded from ...${NC}"
echo -e "   ${GREEN}♻️ Resumed 300 tasks; validator_round_id=...${NC}"
echo -e "   ${GREEN}♻️ Resuming: reusing saved handshake payloads...${NC}"
echo -e "   ${GREEN}⏭️ Skipping task 1: already completed...${NC}"
echo -e "   ${GREEN}⏭️ Skipping task 2: already completed...${NC}"
echo -e "   ${GREEN}...${NC}"
echo ""
echo -e "${YELLOW}If you see these logs, recovery is working! ✅${NC}"
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# Optional: Ask if user wants to run the test now
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                    AUTOMATIC TEST OPTION                       ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
read -p "Do you want to run the automatic test now? (y/N): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo -e "${BLUE}🔄 Running automatic test...${NC}"
    echo ""
    
    # Stop validator
    echo -e "${YELLOW}⏸️  Stopping validator...${NC}"
    pm2 stop "$VALIDATOR_PROCESS" > /dev/null 2>&1
    echo -e "${GREEN}✅ Validator stopped${NC}"
    echo ""
    
    # Wait a bit
    sleep 2
    
    # Verify checkpoint still exists
    if [ -f "$CHECKPOINT_FILE" ]; then
        echo -e "${GREEN}✅ Checkpoint preserved after stop${NC}"
    else
        echo -e "${RED}❌ Checkpoint was deleted! This is a bug.${NC}"
        exit 1
    fi
    echo ""
    
    # Restart validator
    echo -e "${YELLOW}🔄 Restarting validator...${NC}"
    pm2 restart "$VALIDATOR_PROCESS" > /dev/null 2>&1
    echo -e "${GREEN}✅ Validator restarted${NC}"
    echo ""
    
    # Wait for logs
    echo -e "${BLUE}⏳ Waiting 5 seconds for recovery logs...${NC}"
    sleep 5
    echo ""
    
    # Show recovery logs
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                      RECOVERY LOGS                             ║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    RECOVERY_LOGS=$(pm2 logs "$VALIDATOR_PROCESS" --lines 50 --nostream | grep -E "Checkpoint|Resume|Resuming|Skipping" || true)
    
    if [ -n "$RECOVERY_LOGS" ]; then
        echo -e "${GREEN}✅ Recovery logs found:${NC}"
        echo ""
        echo "$RECOVERY_LOGS"
        echo ""
        echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║                  ✅ RECOVERY TEST PASSED                       ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    else
        echo -e "${YELLOW}⚠️  No recovery logs found yet${NC}"
        echo -e "${YELLOW}   This might mean:${NC}"
        echo -e "${YELLOW}   1. Recovery is still in progress (wait a bit)${NC}"
        echo -e "${YELLOW}   2. No tasks were completed before the stop${NC}"
        echo -e "${YELLOW}   3. Logs are not showing the expected format${NC}"
        echo ""
        echo -e "${CYAN}Full recent logs:${NC}"
        pm2 logs "$VALIDATOR_PROCESS" --lines 30 --nostream
    fi
else
    echo ""
    echo -e "${BLUE}👍 Okay, you can run the manual test when ready${NC}"
fi

echo ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                         TEST COMPLETE                          ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

