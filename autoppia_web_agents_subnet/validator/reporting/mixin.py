"""
Reporting mixin for validator - integrates RoundReport into validator lifecycle.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import bittensor as bt

from .round_report import RoundReport, ConsensusValidatorReport
from .email_sender import send_round_report_email

if TYPE_CHECKING:
    from autoppia_web_agents_subnet.validator.base_validator import BaseValidatorNeuron


class ReportingMixin:
    """Mixin to add comprehensive reporting to validator."""
    
    def _init_round_report(
        self,
        round_number: int,
        validator_round_id: str,
        start_block: int,
        start_epoch: float,
        planned_tasks: int,
    ):
        """Initialize RoundReport at the start of a round."""
        validator_uid = getattr(self, "uid", 0)
        validator_hotkey = getattr(self.wallet, "hotkey", None)
        hotkey_str = validator_hotkey.ss58_address if validator_hotkey else "unknown"
        
        self.round_manager.current_round_report = RoundReport(
            round_number=round_number,
            validator_round_id=validator_round_id,
            validator_uid=validator_uid,
            validator_hotkey=hotkey_str,
            start_block=start_block,
            start_epoch=start_epoch,
            planned_tasks=planned_tasks,
        )
        
        bt.logging.info(f"📊 Round report initialized for round {round_number}")
    
    def _report_handshake_sent(self, total_miners: int):
        """Record that handshake was sent to N miners."""
        report = self.round_manager.current_round_report
        if report:
            report.handshake_sent_to = total_miners
    
    def _report_handshake_response(
        self,
        uid: int,
        hotkey: str,
        agent_name: Optional[str] = None,
        agent_image: Optional[str] = None,
    ):
        """Record a miner's handshake response."""
        report = self.round_manager.current_round_report
        if report:
            report.record_handshake_response(uid, hotkey, agent_name, agent_image)
    
    def _report_task_result(
        self,
        uid: int,
        hotkey: str,
        success: bool,
        execution_time: float,
        eval_score: float,
        reward: float,
    ):
        """Record a task execution result."""
        report = self.round_manager.current_round_report
        if report:
            # Ensure miner exists
            report.add_miner(uid, hotkey)
            report.record_task_result(uid, success, execution_time, eval_score, reward)
    
    def _report_consensus_validator(
        self,
        uid: Optional[int],
        hotkey: str,
        stake_tao: float,
        ipfs_cid: Optional[str] = None,
        miners_reported: int = 0,
        miner_scores: Optional[dict] = None,
    ):
        """Record a validator that participated in consensus."""
        report = self.round_manager.current_round_report
        if report:
            validator_report = ConsensusValidatorReport(
                uid=uid,
                hotkey=hotkey,
                stake_tao=stake_tao,
                ipfs_cid=ipfs_cid,
                miners_reported=miners_reported,
                miner_scores=miner_scores or {},
            )
            report.consensus_validators.append(validator_report)
    
    def _report_consensus_published(self, ipfs_cid: str):
        """Record that our consensus was published to IPFS."""
        report = self.round_manager.current_round_report
        if report:
            report.consensus_published = True
            report.consensus_ipfs_cid = ipfs_cid
    
    def _report_consensus_aggregated(self):
        """Record that consensus scores were aggregated."""
        report = self.round_manager.current_round_report
        if report:
            report.consensus_aggregated = True
    
    def _report_set_final_scores(self, final_scores: dict):
        """Set final scores after consensus for all miners."""
        report = self.round_manager.current_round_report
        if report:
            for uid, score in final_scores.items():
                if uid in report.miners:
                    report.miners[uid].final_score_after_consensus = float(score)
    
    def _report_set_winner(self, uid: int, is_local: bool = False):
        """Set the winner of the round."""
        report = self.round_manager.current_round_report
        if report:
            if is_local:
                report.local_winner_uid = uid
            else:
                report.final_winner_uid = uid
            
            if uid in report.miners:
                report.miners[uid].is_winner = True
    
    def _report_set_weights(self, weights: dict):
        """Record final weights for all miners."""
        report = self.round_manager.current_round_report
        if report:
            for uid, weight in weights.items():
                if uid in report.miners:
                    report.miners[uid].final_weight = float(weight)
    
    def _finalize_round_report(self, end_block: int, end_epoch: float):
        """Finalize the round report and send email."""
        report = self.round_manager.current_round_report
        if not report:
            bt.logging.warning("No round report to finalize")
            return
        
        # Finalize report
        report.finalize_round(end_block, end_epoch)
        
        bt.logging.info(f"📊 Round report finalized for round {report.round_number}")
        
        # Save to JSON file
        self._save_round_report_json(report)
        
        # Send email with Codex analysis
        self._send_round_report_email(report)
    
    def _save_round_report_json(self, report: RoundReport):
        """Save round report to JSON file."""
        try:
            repo_root = Path(__file__).resolve().parents[4]
            reports_dir = repo_root / "data" / "round_reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            
            report_file = reports_dir / f"round_{report.round_number}.json"
            
            with open(report_file, 'w') as f:
                json.dump(report.to_dict(), f, indent=2)
            
            bt.logging.success(f"📄 Round report saved to {report_file}")
            
        except Exception as e:
            bt.logging.error(f"Failed to save round report: {e}")
    
    def _send_round_report_email(self, report: RoundReport):
        """Send round report via email with optional Codex analysis."""
        try:
            # Run Codex analysis on logs (optional, with timeout)
            codex_analysis = self._run_codex_analysis(report.round_number)
            
            # Send email
            success = send_round_report_email(report, codex_analysis)
            
            if success:
                bt.logging.success(f"📧 Round report email sent for round {report.round_number}")
            else:
                bt.logging.warning(f"⚠️  Failed to send round report email")
                
        except Exception as e:
            bt.logging.error(f"Error sending round report email: {e}")
    
    def _run_codex_analysis(self, round_number: int, timeout: int = 30) -> Optional[str]:
        """Run Codex analysis on round logs (optional)."""
        try:
            repo_root = Path(__file__).resolve().parents[4]
            codex_script = repo_root / "scripts" / "validator" / "reporting" / "run_codex.sh"
            
            if not codex_script.exists():
                return None
            
            # Get round log file
            round_log = repo_root / "logs" / "rounds" / f"round_{round_number}.log"
            if not round_log.exists():
                return None
            
            # Run Codex with timeout
            result = subprocess.run(
                [str(codex_script), "--round", str(round_number), "--status", "OK"],
                stdin=open(round_log),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
            
            return None
            
        except subprocess.TimeoutExpired:
            bt.logging.warning(f"Codex analysis timed out after {timeout}s")
            return None
        except Exception as e:
            bt.logging.debug(f"Codex analysis failed: {e}")
            return None

