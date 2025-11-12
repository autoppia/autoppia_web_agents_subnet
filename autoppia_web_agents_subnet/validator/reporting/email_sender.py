"""
Email sender for round reports.

Generates beautiful HTML emails from RoundReport objects.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Optional

from .round_report import RoundReport


def generate_html_report(report: RoundReport, codex_analysis: Optional[str] = None) -> str:
    """Generate beautiful HTML email from RoundReport."""

    # Detect environment based on TESTING variable
    is_testing = os.getenv("TESTING", "false").lower() == "true"
    environment = "DEV" if is_testing else "PROD"
    env_color = "#f59e0b" if is_testing else "#22c55e"  # Orange for DEV, Green for PROD
    env_badge = f'<span style="background: {env_color}; color: #0f172a; padding: 4px 12px; border-radius: 999px; font-weight: 600; font-size: 14px; margin-left: 12px;">{environment}</span>'

    # Header
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #050b18; color: #e2e8f0; padding: 40px; }}
            .container {{ max-width: 920px; margin: 0 auto; background: linear-gradient(145deg,#0f172a,#111b30); border: 1px solid rgba(56,189,248,0.16); border-radius: 24px; padding: 44px; }}
            h1 {{ color: #38bdf8; font-size: 32px; margin: 0; }}
            h2 {{ color: #38bdf8; font-size: 24px; margin: 24px 0 12px 0; }}
            h3 {{ color: #38bdf8; font-size: 18px; margin: 20px 0 10px 0; }}
            table {{ width: 100%; border-collapse: collapse; margin: 16px 0; background: rgba(15,23,42,0.92); border-radius: 12px; overflow: hidden; }}
            th {{ background: rgba(56,189,248,0.2); padding: 12px; text-align: left; color: #38bdf8; font-weight: 600; }}
            td {{ padding: 10px 12px; border-bottom: 1px solid rgba(148,163,184,0.18); color: #e2e8f0; }}
            .badge {{ display: inline-block; padding: 4px 12px; border-radius: 999px; font-weight: 600; font-size: 12px; }}
            .badge-success {{ background: #22c55e; color: #0f172a; }}
            .badge-warning {{ background: #f59e0b; color: #0f172a; }}
            .badge-error {{ background: #ef4444; color: #fff; }}
            .winner {{ background: linear-gradient(135deg,#fbbf24,#f59e0b); color: #0f172a; padding: 16px; border-radius: 12px; font-weight: 600; }}
            .codex-section {{ background: rgba(37,99,235,0.12); border: 1px solid rgba(129,140,248,0.35); padding: 18px; border-radius: 14px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎯 Validator Round Report {env_badge}</h1>
            <p style="color: #94a3b8; margin: 8px 0 0 0;">Round {report.round_number} • Validator UID {report.validator_uid}</p>
    """

    # Round Overview
    duration = "In progress"
    if report.end_time and report.start_time:
        duration_seconds = (report.end_time - report.start_time).total_seconds()
        duration = f"{duration_seconds / 60:.1f} minutes"

    html += f"""
            <h2>📊 Round Overview</h2>
            <table>
                <tr><td><strong>Round Number</strong></td><td>{report.round_number}</td></tr>
                <tr><td><strong>Validator Round ID</strong></td><td>{report.validator_round_id}</td></tr>
                <tr><td><strong>Validator Hotkey</strong></td><td>{report.validator_hotkey[:12]}...{report.validator_hotkey[-8:]}</td></tr>
                <tr><td><strong>Start Block</strong></td><td>{report.start_block:,}</td></tr>
                <tr><td><strong>End Block</strong></td><td>{f"{report.end_block:,}" if report.end_block else "In progress"}</td></tr>
                <tr><td><strong>Duration</strong></td><td>{duration}</td></tr>
                <tr><td><strong>Tasks Completed</strong></td><td>{report.tasks_completed}/{report.planned_tasks}</td></tr>
                <tr><td><strong>Status</strong></td><td><span class="badge badge-success">{'Completed' if report.completed else 'In Progress'}</span></td></tr>
            </table>
    """

    # Codex AI Analysis - RIGHT AFTER Overview for maximum visibility
    html += """
        <h2>🤖 Codex AI Analysis</h2>
    """

    if codex_analysis:
        # Format analysis with proper styling
        html += """
            <div style="background: rgba(56,189,248,0.08); border: 1px solid rgba(56,189,248,0.3); padding: 18px; border-radius: 12px;">
        """

        # Convert markdown-style bullets to HTML
        lines = codex_analysis.split("\n")
        in_list = False

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                if in_list:
                    html += "</ul>"
                    in_list = False
                continue

            if line_stripped.startswith("- ") or line_stripped.startswith("• "):
                if not in_list:
                    html += "<ul style='margin: 8px 0; padding-left: 20px;'>"
                    in_list = True
                content = line_stripped[2:].strip()
                html += f"<li style='color: #e2e8f0; margin: 6px 0; line-height: 1.6;'>{content}</li>"
            else:
                if in_list:
                    html += "</ul>"
                    in_list = False
                if line_stripped:
                    html += f"<p style='color: #e2e8f0; margin: 8px 0; line-height: 1.6;'>{line_stripped}</p>"

        if in_list:
            html += "</ul>"

        html += "</div>"
    else:
        html += """
            <div style="background: rgba(148,163,184,0.1); border: 1px solid rgba(148,163,184,0.3); padding: 16px; border-radius: 12px;">
                <p style="color: #94a3b8; margin: 0;">
                    🤖 Codex analysis not available for this round
                </p>
            </div>
        """

    # Round Progress Checklist (NEW)
    html += """
        <h2>✅ Round Progress Checklist</h2>
        <table style="margin-top: 12px;">
            <tr>
                <th style="width: 40%;">Checkpoint</th>
                <th style="width: 20%;">Status</th>
            </tr>
    """

    checkpoints = [
        ("Tasks Generated", getattr(report, "checkpoint_tasks_generated", False)),
        ("Handshake Sent", getattr(report, "checkpoint_handshake_sent", False)),
        ("Tasks Evaluated", getattr(report, "checkpoint_tasks_evaluated", False)),
        ("Publishing Results on IPFS", getattr(report, "checkpoint_ipfs_published", False)),
        ("Downloaded Results from IPFS", getattr(report, "checkpoint_ipfs_downloaded", False)),
        ("Select Winner of Round", getattr(report, "checkpoint_winner_selected", False)),
        ("Set Weights", getattr(report, "checkpoint_weights_set", False)),
    ]

    for checkpoint_name, checkpoint_status in checkpoints:
        if checkpoint_status:
            badge = '<span class="badge badge-success">✓ Done</span>'
        else:
            # If round is completed but checkpoint wasn't done, it's an error
            if report.completed:
                badge = '<span class="badge badge-error">✗ Error</span>'
            else:
                badge = '<span class="badge badge-warning">⏸ Pending</span>'

        html += f"""
            <tr>
                <td>{checkpoint_name}</td>
                <td>{badge}</td>
            </tr>
        """

    html += "</table>"

    # Handshake Results
    html += f"""
            <h2>🤝 Handshake Results</h2>
            <p><strong>{report.handshake_responses}/{report.handshake_sent_to}</strong> miners responded</p>
    """

    if report.handshake_response_uids and len(report.handshake_response_uids) > 0:
        html += """
            <table style="margin-top: 12px;">
                <tr>
                    <th>UID</th>
                    <th>Hotkey</th>
                    <th>Coldkey</th>
                    <th>Miner Name</th>
                    <th>Responded</th>
                </tr>
        """
        for uid, hotkey in zip(report.handshake_response_uids, report.handshake_response_hotkeys):
            miner = report.miners.get(uid)
            coldkey = miner.coldkey[:10] if miner and miner.coldkey else "N/A"
            agent_name = miner.agent_name if miner and miner.agent_name else "N/A"

            html += f"""
                <tr>
                    <td>{uid}</td>
                    <td>{hotkey[:10]}...</td>
                    <td>{coldkey}...</td>
                    <td>{agent_name}</td>
                    <td><span class="badge badge-success">✓ True</span></td>
                </tr>
            """
        html += "</table>"
    else:
        html += "<p style='color: #94a3b8;'>No miners responded to handshake</p>"

    # Miners Evaluated - Main Table
    if report.miners:
        html += f"""
            <h2>⚡ Miners Evaluated</h2>
            <table>
                <tr>
                    <th>#</th>
                    <th>UID</th>
                    <th>Hotkey</th>
                    <th>Coldkey</th>
                    <th>Tasks</th>
                    <th>Score %</th>
                    <th>Avg Time</th>
                    <th>Avg Reward</th>
                </tr>
        """

        sorted_miners = sorted(report.miners.values(), key=lambda m: m.rank if m.rank else 999)

        for miner in sorted_miners:
            row_style = "background: rgba(251,191,36,0.2);" if miner.is_winner else ""
            winner_badge = "🏆 " if miner.is_winner else ""

            # Format: 77/156 (tasks_success/tasks_attempted)
            tasks_display = f"{miner.tasks_success}/{miner.tasks_attempted}"

            # Color by percentage: 0-25 red, 25-50 orange, 50-75 yellow, 75-100 green
            pct = miner.score_percentage
            if pct >= 75:
                pct_color = "#22c55e"  # green
            elif pct >= 50:
                pct_color = "#eab308"  # yellow
            elif pct >= 25:
                pct_color = "#f97316"  # orange
            else:
                pct_color = "#ef4444"  # red

            html += f"""
                <tr style="{row_style}">
                    <td>{winner_badge}{miner.rank}</td>
                    <td>{miner.uid}</td>
                    <td>{miner.hotkey[:10]}...</td>
                    <td>{miner.coldkey[:10] if miner.coldkey else 'N/A'}...</td>
                    <td>{tasks_display}</td>
                    <td><strong style="color: {pct_color};">{miner.score_percentage:.1f}%</strong></td>
                    <td>{miner.avg_time:.2f}s</td>
                    <td>{miner.avg_reward:.4f}</td>
                </tr>
            """

        html += "</table>"

        # Per-Web Statistics for Each Miner
        html += """
            <h3>📊 Per-Web Statistics by Miner</h3>
        """

        for miner in sorted_miners:
            if not miner.per_web_stats:
                continue

            html += f"""
                <h4 style="color: #94a3b8; margin: 16px 0 8px 0;">Miner UID {miner.uid}</h4>
                <table style="font-size: 13px;">
                    <tr>
                        <th>Web</th>
                        <th>Attempted</th>
                        <th>Success</th>
                        <th>Failed</th>
                        <th>Success Rate</th>
                    </tr>
            """

            # Sort webs by name
            for web_name in sorted(miner.per_web_stats.keys()):
                stats = miner.per_web_stats[web_name]
                success_rate = (stats["success"] / stats["attempted"] * 100) if stats["attempted"] > 0 else 0

                # Color by success rate
                if success_rate >= 75:
                    rate_color = "#22c55e"  # green
                elif success_rate >= 50:
                    rate_color = "#eab308"  # yellow
                elif success_rate >= 25:
                    rate_color = "#f97316"  # orange
                else:
                    rate_color = "#ef4444"  # red

                html += f"""
                    <tr>
                        <td><strong>{web_name}</strong></td>
                        <td>{stats["attempted"]}</td>
                        <td><span class="badge badge-success">{stats["success"]}</span></td>
                        <td><span class="badge badge-error">{stats["failed"]}</span></td>
                        <td><strong style="color: {rate_color};">{success_rate:.1f}%</strong></td>
                    </tr>
                """

            html += "</table>"

        # Global Per-Web Summary
        if report.per_web_global_stats:
            html += """
                <h3>🌐 Global Per-Web Summary (All Miners)</h3>
                <table>
                    <tr>
                        <th>Web</th>
                        <th>Total Sent</th>
                        <th>Total Solved</th>
                        <th>Success Rate</th>
                    </tr>
            """

            for web_name in sorted(report.per_web_global_stats.keys()):
                stats = report.per_web_global_stats[web_name]
                success_rate = (stats["solved"] / stats["sent"] * 100) if stats["sent"] > 0 else 0

                # Color by success rate
                if success_rate >= 75:
                    rate_color = "#22c55e"  # green
                elif success_rate >= 50:
                    rate_color = "#eab308"  # yellow
                elif success_rate >= 25:
                    rate_color = "#f97316"  # orange
                else:
                    rate_color = "#ef4444"  # red

                html += f"""
                    <tr>
                        <td><strong>{web_name}</strong></td>
                        <td>{stats["sent"]}</td>
                        <td><span class="badge badge-success">{stats["solved"]}</span></td>
                        <td><strong style="color: {rate_color};">{success_rate:.1f}%</strong></td>
                    </tr>
                """

            html += "</table>"

    # Winner
    if report.final_winner_uid:
        winner = report.miners.get(report.final_winner_uid)
        if winner:
            html += f"""
                <div class="winner">
                    <h2 style="margin: 0; color: #0f172a;">🏆 Winner</h2>
                    <p style="margin: 8px 0 0 0; color: #0f172a; font-size: 18px;">
                        UID {winner.uid} • {winner.hotkey[:12]}...{winner.hotkey[-8:]}
                        <br>Score: {winner.final_score_after_consensus or winner.avg_score:.4f}
                    </p>
                </div>
            """

    # Consensus Validators - Show each validator with their data
    html += """
        <h2>🔗 Consensus Validators</h2>
    """

    # Always show this validator first
    html += f"""
        <h3 style="color: #38bdf8; font-size: 18px; margin-top: 16px;">
            Validator UID {report.validator_uid} • {report.validator_hotkey[:10]}...{report.validator_hotkey[-8:]}
        </h3>
        <p style="color: #94a3b8; font-size: 13px;">
            IPFS CID: <code style="background: rgba(56,189,248,0.1); padding: 2px 6px; border-radius: 4px;">{report.consensus_ipfs_cid[:20] if report.consensus_ipfs_cid else 'Not published'}...</code>
            • Status: <span class="badge badge-{'success' if report.consensus_published else 'warning'}">{'Published' if report.consensus_published else 'Not published'}</span>
        </p>
    """

    # Show this validator's scores
    if report.consensus_published and report.miners:
        html += """
            <table style="font-size: 13px; margin-top: 8px;">
                <tr>
                    <th>Miner UID</th>
                    <th>Hotkey</th>
                    <th>Score Published</th>
                    <th>Tasks</th>
                </tr>
        """

        sorted_by_score = sorted(report.miners.values(), key=lambda m: m.avg_score, reverse=True)
        for miner in sorted_by_score:
            html += f"""
                <tr>
                    <td>{miner.uid}</td>
                    <td>{miner.hotkey[:10]}...</td>
                    <td><strong style="color: #38bdf8;">{miner.avg_score:.4f}</strong></td>
                    <td>{miner.tasks_success}/{miner.tasks_attempted}</td>
                </tr>
            """

        html += "</table>"

    # Show other validators if any
    if report.consensus_validators and len(report.consensus_validators) > 0:
        html += f"""
            <h3 style="color: #94a3b8; font-size: 16px; margin-top: 24px;">Other Validators ({len(report.consensus_validators)})</h3>
        """

        for val in report.consensus_validators:
            html += f"""
                <h4 style="color: #38bdf8; font-size: 16px; margin-top: 16px;">
                    Validator UID {val.uid if val.uid is not None else '?'} • {val.hotkey[:10]}...{val.hotkey[-8:]}
                </h4>
                <p style="color: #94a3b8; font-size: 13px;">
                    Stake: <strong>{val.stake_tao:,.0f} τ</strong> • 
                    IPFS CID: <code style="background: rgba(56,189,248,0.1); padding: 2px 6px; border-radius: 4px;">{val.ipfs_cid[:20] if val.ipfs_cid else 'N/A'}...</code>
                </p>
            """

            # Show their scores if available
            if val.miner_scores:
                html += """
                    <table style="font-size: 13px; margin-top: 8px;">
                        <tr>
                            <th>Miner UID</th>
                            <th>Score Published</th>
                        </tr>
                """

                sorted_scores = sorted(val.miner_scores.items(), key=lambda x: x[1], reverse=True)
                for miner_uid, score in sorted_scores:
                    html += f"""
                        <tr>
                            <td>{miner_uid}</td>
                            <td><strong style="color: #38bdf8;">{score:.4f}</strong></td>
                        </tr>
                    """

                html += "</table>"
    else:
        html += """
            <p style="color: #94a3b8; margin-top: 12px;">No other validators participated in consensus for this round.</p>
        """

    # Top 5 - Table format
    top_5 = report.get_top_miners(5)
    if top_5:
        html += """
            <h2>🏅 Top 5 Miners</h2>
            <table>
                <tr>
                    <th>Rank</th>
                    <th>UID</th>
                    <th>Hotkey</th>
                    <th>Score</th>
                    <th>Tasks</th>
                </tr>
        """

        for idx, miner in enumerate(top_5, start=1):
            score = miner.final_score_after_consensus if miner.final_score_after_consensus > 0 else miner.avg_score
            badge = "🏆" if idx == 1 else f"{idx}"

            html += f"""
                <tr>
                    <td><strong>{badge}</strong></td>
                    <td>{miner.uid}</td>
                    <td>{miner.hotkey[:12]}...</td>
                    <td><strong style="color: #38bdf8;">{score:.4f}</strong></td>
                    <td>{miner.tasks_success}/{miner.tasks_attempted}</td>
                </tr>
            """

        html += "</table>"

    # Errors and Warnings - ALWAYS show section
    errors = getattr(report, "errors", [])
    warnings = getattr(report, "warnings", [])

    # Ensure errors and warnings are lists (defensive programming)
    if not isinstance(errors, list):
        errors = []
    if not isinstance(warnings, list):
        warnings = []

    # Filter out empty strings
    errors = [e for e in errors if e and str(e).strip()]
    warnings = [w for w in warnings if w and str(w).strip()]

    # Log for debugging
    print(f"[EMAIL] Report has {len(errors)} errors and {len(warnings)} warnings")
    if errors:
        print(f"[EMAIL] First 3 errors: {errors[:3]}")

    html += """
        <h2>⚠️ Errors & Warnings</h2>
    """

    if not errors and not warnings:
        html += """
            <p style="color: #22c55e; font-size: 14px;">
                ✅ No errors or warnings detected in this round
            </p>
        """
    else:
        if errors:
            html += f"""
                <h3 style="color: #ef4444; font-size: 16px;">❌ Errors ({len(errors)})</h3>
                <div style="background: rgba(239,68,68,0.1); border-left: 4px solid #ef4444; padding: 12px; border-radius: 8px; margin-bottom: 16px;">
            """
            for idx, error in enumerate(errors[:15], start=1):
                html += f"""
                    <p style="margin: 8px 0; color: #fca5a5; font-size: 13px; font-family: monospace;">
                        {idx}. {error[:200]}{'...' if len(error) > 200 else ''}
                    </p>
                """
            if len(errors) > 15:
                html += f"<p style='color: #94a3b8; font-size: 12px;'>... and {len(errors) - 15} more errors</p>"
            html += "</div>"

        if warnings:
            html += f"""
                <h3 style="color: #f97316; font-size: 16px;">⚠️ Warnings ({len(warnings)})</h3>
                <div style="background: rgba(249,115,22,0.1); border-left: 4px solid #f97316; padding: 12px; border-radius: 8px; margin-bottom: 16px;">
            """
            for idx, warning in enumerate(warnings[:15], start=1):
                html += f"""
                    <p style="margin: 8px 0; color: #fdba74; font-size: 13px; font-family: monospace;">
                        {idx}. {warning[:200]}{'...' if len(warning) > 200 else ''}
                    </p>
                """
            if len(warnings) > 15:
                html += f"<p style='color: #94a3b8; font-size: 12px;'>... and {len(warnings) - 15} more warnings</p>"
            html += "</div>"

    html += """
        </div>
    </body>
    </html>
    """

    return html


def send_round_report_email(report: RoundReport, codex_analysis: Optional[str] = None) -> bool:
    """Send round report via email with beautiful HTML formatting."""

    # Get email config from environment
    smtp_host = os.getenv("REPORT_MONITOR_SMTP_HOST")
    smtp_port = int(os.getenv("REPORT_MONITOR_SMTP_PORT", "587"))
    smtp_user = os.getenv("REPORT_MONITOR_SMTP_USERNAME")
    smtp_pass = os.getenv("REPORT_MONITOR_SMTP_PASSWORD")
    email_from = os.getenv("REPORT_MONITOR_EMAIL_FROM")
    email_to = os.getenv("REPORT_MONITOR_EMAIL_TO")
    use_ssl = os.getenv("REPORT_MONITOR_SMTP_SSL", "false").lower() == "true"

    # Detect environment based on TESTING variable
    is_testing = os.getenv("TESTING", "false").lower() == "true"
    environment = "DEV" if is_testing else "PROD"

    if not smtp_host or not email_to:
        print("❌ Email not configured")
        return False

    # Generate HTML
    html_body = generate_html_report(report, codex_analysis)

    # Generate plain text version
    text_body = f"""
Validator Round Report [{environment}] - Round {report.round_number}

Environment: {environment}
Round: {report.round_number}
Validator UID: {report.validator_uid}
Start Block: {report.start_block:,}
End Block: {f"{report.end_block:,}" if report.end_block else "In progress"}
Tasks: {report.tasks_completed}/{report.planned_tasks}

Handshake: {report.handshake_responses}/{report.handshake_sent_to} miners responded

Miners Evaluated: {len(report.miners)}
"""

    if report.final_winner_uid:
        winner = report.miners.get(report.final_winner_uid)
        if winner:
            text_body += f"\nWinner: UID {winner.uid} (score: {winner.final_score_after_consensus or winner.avg_score:.4f})\n"

    if codex_analysis:
        text_body += f"\n--- Codex Analysis ---\n{codex_analysis}\n"

    # Create email with environment tag in subject
    msg = EmailMessage()
    msg["Subject"] = f"[{environment}] Validator Round {report.round_number} - Complete Report"
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    # Send
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)

        print(f"✅ Email sent to {email_to}")
        return True

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False
