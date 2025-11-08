"""
Codex analyzer for round reports.

Analyzes pickle data + error/warning logs to provide intelligent insights.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

import bittensor as bt

from .round_report import RoundReport


def analyze_round_with_codex(report: RoundReport, timeout: int = 120) -> Optional[str]:
    """
    Analyze round report with Codex AI.

    Provides intelligent insights beyond obvious facts:
    - Consensus discrepancies between validators
    - Web-specific failure patterns
    - Miner behavior anomalies
    - Critical errors requiring attention
    - Non-obvious issues

    Args:
        report: RoundReport to analyze
        timeout: Timeout in seconds (default 120)

    Returns:
        Codex analysis as string, or None if unavailable
    """
    try:
        # Build comprehensive context for Codex
        context = _build_codex_context(report)

        # Build intelligent prompt
        prompt = _build_codex_prompt(report, context)

        # Call Codex via subprocess
        result = subprocess.run(
            ["codex"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode == 0 and result.stdout:
            analysis = result.stdout.strip()
            if analysis and len(analysis) > 50:
                return analysis

        return None

    except subprocess.TimeoutExpired:
        bt.logging.warning(f"Codex analysis timed out after {timeout}s")
        return None
    except FileNotFoundError:
        bt.logging.debug("Codex CLI not found")
        return None
    except Exception as e:
        bt.logging.debug(f"Codex analysis failed: {e}")
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


def _build_codex_prompt(report: RoundReport, context: dict) -> str:
    """Build intelligent prompt for Codex."""

    prompt = f"""You are analyzing a Bittensor validator round. Provide INTELLIGENT INSIGHTS beyond obvious facts.

=== ROUND {report.round_number} - VALIDATOR UID {report.validator_uid} ===

CHECKPOINTS (what happened):
{json.dumps(context['checkpoints'], indent=2)}

MINERS EVALUATED:
{json.dumps(context['miners'], indent=2)}

PER-WEB SUCCESS RATES:
{json.dumps(context['per_web_stats'], indent=2)}

CONSENSUS:
- Published to IPFS: {context['consensus']['published']}
- Other validators participating: {context['consensus']['other_validators']}

ERRORS: {context['errors_count']}
WARNINGS: {context['warnings_count']}
"""

    # Add errors if any
    if report.errors:
        prompt += f"\n\nERRORS DETECTED ({len(report.errors)}):\n"
        for idx, error in enumerate(report.errors[:10], start=1):
            prompt += f"{idx}. {error[:150]}\n"

    # Add warnings if any
    if report.warnings:
        prompt += f"\n\nWARNINGS DETECTED ({len(report.warnings)}):\n"
        for idx, warning in enumerate(report.warnings[:10], start=1):
            prompt += f"{idx}. {warning[:150]}\n"

    # Add consensus validator comparison if available
    if report.consensus_validators:
        prompt += "\n\nOTHER VALIDATORS:\n"
        for val in report.consensus_validators:
            prompt += f"- Validator UID {val.uid}: {val.miners_reported} miners, stake {val.stake_tao:.0f}τ\n"

    # Intelligent analysis instructions
    prompt += """

=== ANALYSIS INSTRUCTIONS ===

Provide a concise analysis (max 300 words) focusing on:

1. NON-OBVIOUS ISSUES:
   - Don't state obvious facts (e.g., "6 tasks completed")
   - Focus on ANOMALIES and PATTERNS
   
2. WEB-SPECIFIC PROBLEMS:
   - If a web has 0% success across ALL miners → likely web is down
   - If one web has much lower success → investigate that web
   
3. MINER BEHAVIOR:
   - If a miner always fails → might be broken
   - If a miner has inconsistent performance → investigate
   
4. CONSENSUS DISCREPANCIES:
   - If validators disagree significantly → explain why
   - If no other validators → note this (testing mode?)
   
5. CRITICAL ERRORS:
   - Highlight errors that need immediate attention
   - Ignore routine warnings
   
6. RECOMMENDATIONS:
   - What should be investigated?
   - What actions to take?

FORMAT:
- Use bullet points
- Be specific (mention UIDs, web names, error types)
- Focus on ACTIONABLE insights
- If everything looks normal, say so briefly

ANALYSIS:
"""

    return prompt


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
