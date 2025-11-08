"""
Reporting mixin for validator - integrates RoundReport into validator lifecycle.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional, Any

import bittensor as bt

from .round_report import RoundReport, ConsensusValidatorReport
from .email_sender import send_round_report_email


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
        coldkey: str,
        success: bool,
        execution_time: float,
        eval_score: float,
        reward: float,
        web_name: Optional[str] = None,
    ):
        """Record a task execution result."""
        report = self.round_manager.current_round_report
        if report:
            # Ensure miner exists
            miner = report.add_miner(uid, hotkey)
            if coldkey and not miner.coldkey:
                miner.coldkey = coldkey

            report.record_task_result(uid, success, execution_time, eval_score, reward, web_name)

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

    def _report_error(self, error_message: str):
        """Record an error that occurred during the round."""
        report = self.round_manager.current_round_report
        if report:
            report.add_error(error_message)

    def _report_warning(self, warning_message: str):
        """Record a warning that occurred during the round."""
        report = self.round_manager.current_round_report
        if report:
            report.add_warning(warning_message)

    def _finalize_round_report(self, end_block: int, end_epoch: float, tasks_completed: int = 0):
        """Finalize the round report and send email."""
        report = self.round_manager.current_round_report
        if not report:
            bt.logging.warning("No round report to finalize (was round resumed from checkpoint?)")
            bt.logging.info("Skipping round report email for this round")
            return

        # Update tasks completed
        report.tasks_completed = tasks_completed

        # Extract errors/warnings from round logs
        self._extract_errors_warnings_from_logs(report)

        # Finalize report
        report.finalize_round(end_block, end_epoch)

        bt.logging.info(f"📊 Round report finalized for round {report.round_number}")

        # Save to pickle file (for future retrieval)
        self._save_round_report_pickle(report)

        # Send email with Codex analysis (ALWAYS, even if errors)
        self._send_round_report_email(report)

        # Clear from memory
        self.round_manager.current_round_report = None
        bt.logging.debug("Round report cleared from memory")

    def _extract_errors_warnings_from_logs(self, report: RoundReport):
        """Extract errors and warnings from round log file."""
        try:
            repo_root = Path(__file__).resolve().parents[4]
            round_log = repo_root / "data" / "logs" / "rounds" / f"round_{report.round_number}.log"

            if not round_log.exists():
                return

            # Read log file and extract ERROR and WARNING lines
            with open(round_log, "r") as f:
                for line in f:
                    line_clean = line.strip()

                    if "ERROR" in line and "ERROR" in line_clean:
                        # Extract just the message part
                        if "|" in line_clean:
                            parts = line_clean.split("|")
                            if len(parts) >= 3:
                                message = parts[-1].strip()
                                report.add_error(message)

                    elif "WARNING" in line or "⚠️" in line:
                        if "|" in line_clean:
                            parts = line_clean.split("|")
                            if len(parts) >= 3:
                                message = parts[-1].strip()
                                report.add_warning(message)

        except Exception as e:
            bt.logging.debug(f"Failed to extract errors/warnings from logs: {e}")

    def _save_round_report_pickle(self, report: RoundReport):
        """Save round report to pickle file for future retrieval."""
        try:
            import pickle

            repo_root = Path(__file__).resolve().parents[4]
            reports_dir = repo_root / "data" / "reports" / "rounds"
            reports_dir.mkdir(parents=True, exist_ok=True)

            report_file = reports_dir / f"round_{report.round_number}.pkl"

            with open(report_file, "wb") as f:
                pickle.dump(report, f)

            bt.logging.success(f"📄 Round report saved to {report_file}")

        except Exception as e:
            bt.logging.error(f"Failed to save round report: {e}")

    def _send_round_report_email(self, report: RoundReport):
        """
        Send round report via email with optional Codex analysis.

        ALWAYS sends email, even if there were errors during the round.
        This ensures we're notified of any issues.
        """
        try:
            # Run Codex analysis on logs (optional, with timeout)
            # Codex only analyzes logs for warnings/errors, not extracting data
            codex_analysis = None
            try:
                codex_analysis = self._run_codex_analysis(report.round_number)
            except Exception as e:
                bt.logging.debug(f"Codex analysis failed: {e}")

            # Send email (ALWAYS, even if round had errors)
            success = send_round_report_email(report, codex_analysis)

            if success:
                bt.logging.success(f"📧 Round report email sent for round {report.round_number}")
            else:
                bt.logging.warning(f"⚠️  Failed to send round report email (but round data is saved)")

        except Exception as e:
            bt.logging.error(f"Error sending round report email: {e} (round data is still saved)")

    @staticmethod
    def load_round_report(round_number: int) -> Optional[RoundReport]:
        """Load a round report from pickle file."""
        try:
            import pickle

            repo_root = Path(__file__).resolve().parents[4]
            report_file = repo_root / "data" / "reports" / "rounds" / f"round_{round_number}.pkl"

            if not report_file.exists():
                return None

            with open(report_file, "rb") as f:
                return pickle.load(f)

        except Exception as e:
            bt.logging.error(f"Failed to load round report {round_number}: {e}")
            return None

    @staticmethod
    def resend_round_report(round_number: int) -> bool:
        """Load and resend email for a past round."""
        report = ReportingMixin.load_round_report(round_number)

        if not report:
            bt.logging.error(f"Round report {round_number} not found")
            return False

        bt.logging.info(f"📧 Resending report for round {round_number}")

        # Run Codex analysis
        try:
            codex_analysis = ReportingMixin._run_codex_analysis_static(round_number)
        except:
            codex_analysis = None

        # Send email
        success = send_round_report_email(report, codex_analysis)

        if success:
            bt.logging.success(f"✅ Report resent for round {round_number}")
        else:
            bt.logging.error(f"❌ Failed to resend report for round {round_number}")

        return success

    @staticmethod
    def _run_codex_analysis_static(round_number: int, timeout: int = 30) -> Optional[str]:
        """Static version of Codex analysis (for resending old reports)."""
        try:
            repo_root = Path(__file__).resolve().parents[4]
            codex_script = repo_root / "scripts" / "validator" / "reporting" / "run_codex.sh"

            if not codex_script.exists():
                return None

            round_log = repo_root / "data" / "logs" / "rounds" / f"round_{round_number}.log"
            if not round_log.exists():
                return None

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

        except:
            return None

    def _run_codex_analysis(self, round_number: int, timeout: int = 30) -> Optional[str]:
        """Run Codex analysis on round logs (optional)."""
        try:
            repo_root = Path(__file__).resolve().parents[4]
            codex_script = repo_root / "scripts" / "validator" / "reporting" / "run_codex.sh"

            if not codex_script.exists():
                return None

            # Get round log file
            round_log = repo_root / "data" / "logs" / "rounds" / f"round_{round_number}.log"
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
