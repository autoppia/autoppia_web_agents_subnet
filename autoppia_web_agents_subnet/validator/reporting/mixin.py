"""
Reporting mixin for validator - integrates RoundReport into validator lifecycle.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import bittensor as bt

from .round_report import RoundReport, ConsensusValidatorReport
from .email_sender import send_round_report_email
from .codex_analyzer import analyze_round_with_codex


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

        # Mark tasks generated checkpoint
        self.round_manager.current_round_report.checkpoint_tasks_generated = True

        bt.logging.info(f"📊 Round report initialized for round {round_number}")

    def _report_handshake_sent(self, total_miners: int):
        """Record that handshake was sent to N miners."""
        report = self.round_manager.current_round_report
        if report:
            report.handshake_sent_to = total_miners
            report.checkpoint_handshake_sent = True
            # Save incremental pickle after handshake
            self._save_round_report_pickle(report, incremental=True)

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
            report.checkpoint_tasks_evaluated = True

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
            report.checkpoint_ipfs_published = True

    def _report_consensus_aggregated(self):
        """Record that consensus scores were aggregated."""
        report = self.round_manager.current_round_report
        if report:
            report.consensus_aggregated = True
            report.checkpoint_ipfs_downloaded = True

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

            report.checkpoint_winner_selected = True

    def _report_set_weights(self, weights: dict):
        """Record final weights for all miners."""
        report = self.round_manager.current_round_report
        if report:
            for uid, weight in weights.items():
                if uid in report.miners:
                    report.miners[uid].final_weight = float(weight)

    def _report_weights_set(self, success: bool = True):
        """Record that weights were set on chain (or attempted)."""
        report = self.round_manager.current_round_report
        if report:
            report.checkpoint_weights_set = success

    def _report_error(self, error_message: str):
        """Record an error that occurred during the round."""
        if not error_message:
            bt.logging.warning("_report_error called with empty message")
            return

        report = self.round_manager.current_round_report
        if report:
            bt.logging.debug(f"Adding error to report: {error_message[:100]}")
            report.add_error(error_message)
            bt.logging.debug(f"Report now has {len(report.errors)} total errors")
        else:
            bt.logging.warning(f"Could not report error (no active round report): {error_message[:100]}")

    def _report_warning(self, warning_message: str):
        """Record a warning that occurred during the round."""
        report = self.round_manager.current_round_report
        if report:
            report.add_warning(warning_message)

    def _finalize_round_report(self, end_block: int, end_epoch: float, tasks_completed: int = 0):
        """Finalize the round report and send email."""
        report = self.round_manager.current_round_report
        if not report:
            bt.logging.warning("No round report to finalize")
            bt.logging.info("Skipping round report email for this round")
            return

        # Update tasks completed
        report.tasks_completed = tasks_completed

        # Extract errors/warnings from round logs
        self._extract_errors_warnings_from_logs(report)

        # Log errors/warnings before finalizing
        bt.logging.info(f"📊 Finalizing round report for round {report.round_number}")
        bt.logging.info(f"   Errors captured: {len(report.errors)}")
        bt.logging.info(f"   Warnings captured: {len(report.warnings)}")
        if report.errors:
            for idx, err in enumerate(report.errors[:5], 1):
                bt.logging.info(f"   Error {idx}: {err[:150]}")

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
        """Extract errors and warnings from log files (round-specific or PM2 fallback)."""
        try:
            log_sources = []

            # 1. Try round-specific log file first (preferred and isolated)
            repo_root = Path(__file__).resolve().parents[3]
            round_log = repo_root / "data" / "logs" / "rounds" / f"round_{report.round_number}.log"
            if round_log.exists():
                log_sources.append(("round", round_log))
                bt.logging.debug(f"Using round-specific log: {round_log}")
            else:
                bt.logging.warning(f"Round-specific log not found: {round_log}")
                bt.logging.info("Will attempt to extract errors from PM2 logs using timestamp filtering")

                # Fallback to PM2 logs with timestamp filtering
                # Try common PM2 log locations
                home = Path.home()
                pm2_logs = [
                    home / ".pm2/logs/validator-wta-out.log",
                    home / ".pm2/logs/validator-out.log",
                ]

                for pm2_log in pm2_logs:
                    if pm2_log.exists():
                        log_sources.append(("pm2", pm2_log))
                        bt.logging.info(f"Using PM2 log as fallback: {pm2_log}")
                        break

                if not log_sources:
                    bt.logging.warning("No log sources available; errors/warnings will only come from in-memory captures")
                    return

            # Compile regex patterns once
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

            # Calculate round time window for PM2 log filtering
            # Format: 2025-11-12 10:52:18.546
            round_start_time = report.start_time
            round_end_time = report.end_time if report.end_time else None

            bt.logging.debug(f"Round time window: {round_start_time} to {round_end_time}")

            # Process all log sources
            for log_type, log_path in log_sources:
                try:
                    # For large log files, only read the last part relevant to this round
                    # For PM2 logs, read more lines to ensure we capture the full round
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        max_lines = 20000 if log_type == "pm2" else 10000
                        lines_to_process = lines[-max_lines:] if len(lines) > max_lines else lines

                        errors_found = 0
                        warnings_found = 0

                        for line in lines_to_process:
                            line_clean = line.strip()

                            # Skip empty lines
                            if not line_clean:
                                continue

                            # Remove ANSI color codes (from loguru and bittensor)
                            line_clean = ansi_escape.sub("", line_clean)

                            # For PM2 logs, filter by timestamp
                            if log_type == "pm2":
                                # Try to extract timestamp from various formats
                                timestamp_str = None

                                # PM2 format: "2|validato | [34m2025-11-12 10:52:18.546[39m | ..."
                                # or IWA format: "2025-11-12 10:49:57 | ERROR | ..."
                                if line_clean.startswith("2|"):
                                    # Find timestamp pattern after "2|validato | "
                                    match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line_clean)
                                    if match:
                                        timestamp_str = match.group(1)
                                elif re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line_clean):
                                    # Direct format from IWA module
                                    timestamp_str = line_clean[:19]  # "2025-11-12 10:49:57"

                                # Filter by round time window
                                if timestamp_str and round_start_time:
                                    try:
                                        line_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                                        # Skip lines before round start
                                        if line_time < round_start_time.replace(microsecond=0):
                                            continue

                                        # Skip lines after round end (if round is completed)
                                        if round_end_time and line_time > round_end_time.replace(microsecond=0):
                                            continue
                                    except Exception:
                                        pass  # If timestamp parsing fails, include the line anyway

                            # Parse different log formats

                            # Format 1: IWA module format "YYYY-MM-DD HH:MM:SS | LEVEL | message"
                            if "|" in line_clean and not line_clean.startswith("2|"):
                                parts = line_clean.split("|")
                                if len(parts) >= 3:
                                    level = parts[1].strip().upper()

                                    if level == "ERROR":
                                        message = "|".join(parts[2:]).strip()
                                        if message and len(message) > 10:
                                            report.add_error(message)
                                            errors_found += 1

                                    elif level == "WARNING":
                                        message = "|".join(parts[2:]).strip()
                                        if message and len(message) > 10:
                                            report.add_warning(message)
                                            warnings_found += 1

                            # Format 2: PM2 bittensor format "2|validato | [timestamp] | [level] | module | message"
                            elif line_clean.startswith("2|"):
                                # Extract the level and message after removing PM2 prefix and timestamp
                                # Look for ERROR or WARNING markers

                                if "ERROR" in line_clean:
                                    # Find where ERROR appears (it might be styled or plain)
                                    idx = line_clean.find("ERROR")
                                    if idx > 0:
                                        # Get everything after ERROR, split by | to find message
                                        after_error = line_clean[idx + 5 :].strip()
                                        # Skip the first | which is usually module separator
                                        parts = after_error.split("|", 1)
                                        message = parts[1].strip() if len(parts) > 1 else after_error.strip()

                                        if message and len(message) > 10:
                                            # Clean up common artifacts
                                            message = message.replace("[39m[49m[0m", "").replace("[0m", "").strip()
                                            if message:
                                                report.add_error(message)
                                                errors_found += 1

                                elif "WARNING" in line_clean:
                                    idx = line_clean.find("WARNING")
                                    if idx > 0:
                                        after_warning = line_clean[idx + 7 :].strip()
                                        parts = after_warning.split("|", 1)
                                        message = parts[1].strip() if len(parts) > 1 else after_warning.strip()

                                        if message and len(message) > 10:
                                            message = message.replace("[39m[49m[0m", "").replace("[0m", "").strip()
                                            if message:
                                                report.add_warning(message)
                                                warnings_found += 1

                        bt.logging.info(f"Extracted {errors_found} errors and {warnings_found} warnings from {log_type} log")

                except Exception as log_exc:
                    bt.logging.debug(f"Failed to parse log file {log_path}: {log_exc}")

        except Exception as e:
            bt.logging.debug(f"Failed to extract errors/warnings from logs: {e}")

    def _save_round_report_pickle(self, report: RoundReport, incremental: bool = False):
        """
        Save round report to pickle file for future retrieval.

        Args:
            report: RoundReport to save
            incremental: If True, this is an incremental save (don't log as much)
        """
        try:
            import pickle

            repo_root = Path(__file__).resolve().parents[3]
            reports_dir = repo_root / "data" / "reports" / "rounds"
            reports_dir.mkdir(parents=True, exist_ok=True)

            report_file = reports_dir / f"round_{report.round_number}.pkl"

            with open(report_file, "wb") as f:
                pickle.dump(report, f)

            if incremental:
                bt.logging.debug(f"📄 Incremental save: round_{report.round_number}.pkl")
            else:
                bt.logging.success(f"📄 Round report saved to {report_file}")

        except Exception as e:
            bt.logging.error(f"Failed to save round report: {e}")

    def _send_round_report_email(self, report: RoundReport):
        """
        Send round report via email with Codex AI analysis.

        ALWAYS sends email, even if there were errors during the round.
        This ensures we're notified of any issues.
        """
        try:
            # Run Codex analysis on pickle + errors/warnings (120s timeout)
            # Codex analyzes structured data for intelligent insights
            codex_analysis = None
            try:
                bt.logging.info("🤖 Running Codex analysis on round data...")
                codex_analysis = analyze_round_with_codex(report, timeout=120)
                if codex_analysis:
                    bt.logging.success("✅ Codex analysis completed")
                else:
                    bt.logging.info("ℹ️  Codex analysis not available")
            except Exception as e:
                bt.logging.debug(f"Codex analysis failed: {e}")

            # Log errors/warnings before sending email (for debugging)
            bt.logging.info(f"📧 Preparing to send email for round {report.round_number}")
            bt.logging.info(f"   Report errors count: {len(report.errors)}")
            bt.logging.info(f"   Report warnings count: {len(report.warnings)}")
            if report.errors:
                bt.logging.info("   Errors to include in email:")
                for idx, err in enumerate(report.errors[:10], 1):
                    bt.logging.info(f"      {idx}. {err[:200]}")

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

            repo_root = Path(__file__).resolve().parents[3]
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
            repo_root = Path(__file__).resolve().parents[3]
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
            repo_root = Path(__file__).resolve().parents[3]
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
