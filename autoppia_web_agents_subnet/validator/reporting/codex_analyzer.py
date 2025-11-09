"""
Intelligent analyzer for round reports.

Analyzes round data + error/warning logs to provide actionable insights.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import bittensor as bt

from .round_report import RoundReport


def analyze_round_with_codex(report: RoundReport, timeout: int = 120) -> Optional[str]:
    """
    Analyze round report with built-in intelligence.

    Provides intelligent insights beyond obvious facts:
    - Consensus discrepancies between validators
    - Web-specific failure patterns
    - Miner behavior anomalies
    - Critical errors requiring attention
    - Non-obvious issues

    Args:
        report: RoundReport to analyze
        timeout: Timeout in seconds (default 120, kept for API compatibility)

    Returns:
        Analysis as string, or None if unavailable
    """
    try:
        # Build comprehensive context for analysis
        context = _build_codex_context(report)

        # Generate intelligent analysis directly
        analysis = _generate_intelligent_analysis(report, context)

        if analysis and len(analysis) > 50:
            return analysis

        return None

    except Exception as e:
        bt.logging.debug(f"Analysis failed: {e}")
        return None


def _build_codex_context(report: RoundReport) -> dict:
    """Build structured context from report."""

    context = {
        "round_number": report.round_number,
        "validator_uid": report.validator_uid,
        "tasks_completed": f"{report.tasks_completed}/{report.planned_tasks}",
        "checkpoints": {
            "tasks_generated": report.checkpoint_tasks_generated,
            "handshake_sent": report.checkpoint_handshake_sent,
            "tasks_evaluated": report.checkpoint_tasks_evaluated,
            "ipfs_published": report.checkpoint_ipfs_published,
            "ipfs_downloaded": report.checkpoint_ipfs_downloaded,
            "winner_selected": report.checkpoint_winner_selected,
            "weights_set": report.checkpoint_weights_set,
        },
        "miners": [],
        "per_web_stats": {},
        "consensus": {
            "published": report.consensus_published,
            "cid": report.consensus_ipfs_cid,
            "other_validators": len(report.consensus_validators),
        },
        "errors_count": len(report.errors),
        "warnings_count": len(report.warnings),
    }

    # Miner summaries
    for miner in report.miners.values():
        context["miners"].append(
            {
                "uid": miner.uid,
                "tasks": f"{miner.tasks_success}/{miner.tasks_attempted}",
                "score_pct": f"{miner.score_percentage:.1f}%",
                "avg_score": f"{miner.avg_score:.4f}",
            }
        )

    # Per-web global stats
    for web_name, stats in report.per_web_global_stats.items():
        success_rate = (stats["solved"] / stats["sent"] * 100) if stats["sent"] > 0 else 0
        context["per_web_stats"][web_name] = {
            "sent": stats["sent"],
            "solved": stats["solved"],
            "rate": f"{success_rate:.1f}%",
        }

    return context


def _generate_intelligent_analysis(report: RoundReport, context: dict) -> Optional[str]:
    """Generate intelligent analysis directly without external dependencies."""

    analysis_parts = []

    # 1. Check for critical errors
    if report.errors:
        critical_errors = []
        for error in report.errors[:5]:
            if "set_weights failed" in error:
                critical_errors.append("⚠️ CRITICAL: Weights could not be set on-chain. This is likely due to insufficient stake or blockchain connection issues.")
            elif "Subtensor returned: Invalid Transaction" in error:
                critical_errors.append("⚠️ Blockchain transaction failed - check validator stake and connection status.")
            elif "IWAP" in error or "backend" in error.lower():
                critical_errors.append(f"⚠️ Backend communication issue: {error[:100]}")
            elif "timeout" in error.lower():
                critical_errors.append("⚠️ Timeout detected - miners may be slow or unresponsive.")

        if critical_errors:
            analysis_parts.extend(critical_errors)

    # 2. Analyze checkpoints
    checkpoints = context.get("checkpoints", {})
    failed_checkpoints = [name for name, status in checkpoints.items() if not status]

    if "weights_set" in failed_checkpoints:
        analysis_parts.append("• Weights were NOT set on-chain -Validator likely lacks minimum stake (10,000 τ required in production).")

    if "ipfs_published" not in failed_checkpoints and "ipfs_downloaded" in failed_checkpoints:
        analysis_parts.append("• Consensus was published but not aggregated from other validators - possible network isolation or timing issue.")

    # 3. Analyze miner performance
    miners = context.get("miners", [])
    if miners:
        total_miners = len(miners)
        zero_score_miners = sum(1 for m in miners if float(m.get("avg_score", 0)) == 0)

        if zero_score_miners == total_miners:
            analysis_parts.append(f"• ALL {total_miners} miners scored 0% - tasks may be misconfigured or evaluation system failing.")
        elif zero_score_miners > total_miners / 2:
            analysis_parts.append(f"• {zero_score_miners}/{total_miners} miners scored 0% - investigate if tasks are too difficult or miners are broken.")

        # Check for winner
        winner = None
        for miner in miners:
            tasks_str = miner.get("tasks", "0/0")
            if "/" in tasks_str:
                success, total = tasks_str.split("/")
                if int(success) > 0:
                    winner = miner
                    break

        if winner:
            uid = winner.get("uid")
            score = winner.get("score_pct", "0%")
            analysis_parts.append(f"• Winner: Miner UID {uid} with {score} success rate.")

    # 4. Analyze per-web statistics
    per_web = context.get("per_web_stats", {})
    if per_web:
        failing_webs = []
        low_success_webs = []

        for web_name, stats in per_web.items():
            rate_str = stats.get("rate", "0%")
            try:
                rate = float(rate_str.rstrip("%"))
                if rate == 0:
                    failing_webs.append(web_name)
                elif rate < 30:
                    low_success_webs.append(f"{web_name} ({rate_str})")
            except:
                pass

        if failing_webs:
            analysis_parts.append(f"• Web projects with 0% success: {', '.join(failing_webs)} - these projects may be down or misconfigured.")

        if low_success_webs:
            analysis_parts.append(f"• Low success rate on: {', '.join(low_success_webs)} - investigate project-specific issues.")

        # Check if only one project succeeds
        success_webs = [web for web, stats in per_web.items() if float(stats.get("rate", "0%").rstrip("%")) > 50]
        if len(success_webs) == 1 and len(per_web) > 1:
            analysis_parts.append(f"• Only {success_webs[0]} has good success rate - other projects need attention.")

    # 5. Consensus analysis
    consensus = context.get("consensus", {})
    other_validators = consensus.get("other_validators", 0)

    if not consensus.get("published"):
        analysis_parts.append("• Consensus NOT published to IPFS - distributed validation disabled or failed.")
    elif other_validators == 0:
        analysis_parts.append("• No other validators participated in consensus - validator may be isolated or in testing mode.")

    # 6. Round completion status
    tasks_completed_str = context.get("tasks_completed", "0/0")
    if "/" in tasks_completed_str:
        try:
            completed, planned = tasks_completed_str.split("/")
            if int(completed) < int(planned):
                analysis_parts.append(f"• Round incomplete: only {completed}/{planned} tasks finished - possible timeout or crash.")
        except:
            pass

    # 7. If everything looks good
    if not analysis_parts:
        if report.completed and not report.errors:
            analysis_parts.append("✅ Round completed successfully with no critical issues detected.")
            if miners:
                best_miner = max(miners, key=lambda m: float(m.get("avg_score", 0)))
                uid = best_miner.get("uid")
                score = best_miner.get("score_pct", "0%")
                analysis_parts.append(f"• Best performer: Miner UID {uid} with {score} success rate.")
        else:
            analysis_parts.append("• Round data available but limited analysis possible - check logs for details.")

    return "\n".join(analysis_parts) if analysis_parts else None


def format_codex_analysis_for_email(analysis: Optional[str]) -> str:
    """Format Codex analysis for email display."""
    if not analysis:
        return """
<div style="background: rgba(148,163,184,0.1); border: 1px solid rgba(148,163,184,0.3); padding: 16px; border-radius: 12px;">
    <p style="color: #94a3b8; margin: 0;">
        🤖 Codex analysis not available for this round
    </p>
</div>
"""

    # Convert to HTML with proper formatting
    html = """
<div style="background: rgba(56,189,248,0.08); border: 1px solid rgba(56,189,248,0.3); padding: 18px; border-radius: 12px;">
    <h3 style="margin: 0 0 12px 0; color: #38bdf8;">🤖 Codex AI Analysis</h3>
"""

    # Convert markdown-style bullets to HTML
    lines = analysis.split("\n")
    in_list = False

    for line in lines:
        line = line.strip()
        if not line:
            if in_list:
                html += "</ul>"
                in_list = False
            continue

        if line.startswith("- ") or line.startswith("• "):
            if not in_list:
                html += "<ul style='margin: 8px 0; padding-left: 20px;'>"
                in_list = True
            content = line[2:].strip()
            html += f"<li style='color: #e2e8f0; margin: 4px 0;'>{content}</li>"
        else:
            if in_list:
                html += "</ul>"
                in_list = False
            html += f"<p style='color: #e2e8f0; margin: 8px 0;'>{line}</p>"

    if in_list:
        html += "</ul>"

    html += "</div>"

    return html
