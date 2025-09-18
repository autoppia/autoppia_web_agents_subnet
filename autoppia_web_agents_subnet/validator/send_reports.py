#!/usr/bin/env python3
# send_reports.py
import os
import json
import smtplib
import socket
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from collections import defaultdict

# 1) Cargar .env  (pip install python-dotenv)
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass  # si no está instalado, os.getenv seguirá funcionando si ya exportaste vars

# 2) Rutas de entrada
FORWARD_JSONL = Path("reports/forward_summary.jsonl")  # lo escribes en el hook del forward
COLDKEY_SNAPSHOT = Path("coldkey_web_usecase_stats.json")  # ya lo mantiene vuestro código


# 3) Config del email desde .env
def load_cfg():
    to_emails = [e.strip() for e in os.getenv("SMTP_TO", "").split(",") if e.strip()]
    return {
        "smtp_host": os.getenv("SMTP_HOST", "localhost"),
        "smtp_port": int(os.getenv("SMTP_PORT", "25")),
        "smtp_user": os.getenv("SMTP_USER") or None,
        "smtp_pass": os.getenv("SMTP_PASS") or None,
        "from_email": os.getenv("SMTP_FROM", "reports@localhost"),
        "to_emails": to_emails,
        "starttls": os.getenv("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes"),
    }


# 4) Utilidades
def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def render_table(headers, rows):
    if not rows:
        return "(sin datos)"
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    line_h = "|" + "|".join(f" {headers[i]:<{widths[i]}} " for i in range(len(headers))) + "|"
    line_rows = ["|" + "|".join(f" {str(r[i]):<{widths[i]}} " for i in range(len(headers))) + "|" for r in rows]
    return "\n".join([sep, line_h, sep] + line_rows + [sep])


# 5) Cargar totales de forward (acumulado y por forward)
def load_forward_totals():
    totals = {
        "forwards": 0,
        "tasks_sent": 0,
        "miner_successes": 0,
        "miner_attempts": 0,
        "forward_time_sum": 0.0,
        "avg_response_time_sum": 0.0,
        "avg_response_time_count": 0,
    }
    per_forward_rows = []
    if FORWARD_JSONL.exists():
        for line in FORWARD_JSONL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            fid = rec.get("forward_id", "-")
            tasks_sent = safe_int(rec.get("tasks_sent", 0))
            fwd_time = safe_float(rec.get("forward_time", 0.0))
            miner_succ = safe_int(rec.get("miner_successes", 0))
            miner_atts = safe_int(rec.get("miner_attempts", 0))
            avg_resp = rec.get("avg_response_time", None)

            totals["forwards"] += 1
            totals["tasks_sent"] += tasks_sent
            totals["miner_successes"] += miner_succ
            totals["miner_attempts"] += miner_atts
            totals["forward_time_sum"] += fwd_time
            if avg_resp is not None:
                totals["avg_response_time_sum"] += safe_float(avg_resp, 0.0)
                totals["avg_response_time_count"] += 1

            per_forward_rows.append(
                [
                    fid,
                    tasks_sent,
                    miner_succ,
                    miner_atts,
                    f"{(miner_succ / miner_atts * 100):.1f}%" if miner_atts else "0.0%",
                    f"{fwd_time:.2f}s",
                ]
            )

    success_rate = (totals["miner_successes"] / totals["miner_attempts"] * 100) if totals["miner_attempts"] else 0.0
    avg_forward_time = (totals["forward_time_sum"] / totals["forwards"]) if totals["forwards"] else 0.0
    avg_response_time = totals["avg_response_time_sum"] / totals["avg_response_time_count"] if totals["avg_response_time_count"] else 0.0

    total_row = [
        "TOTAL",
        totals["tasks_sent"],
        totals["miner_successes"],
        totals["miner_attempts"],
        f"{success_rate:.1f}%",
        f"{avg_forward_time:.2f}s",
    ]
    headers = ["Forward", "Tasks", "Successes", "Attempts", "Succ %", "Forward Time"]
    table_per_forward = render_table(headers, per_forward_rows + ([total_row] if per_forward_rows else []))

    summary = {
        "total_forwards": totals["forwards"],
        "total_tasks_sent": totals["tasks_sent"],
        "miner_success_rate": f"{success_rate:.1f}%",
        "avg_forward_time": f"{avg_forward_time:.2f}s",
        "avg_response_time": f"{avg_response_time:.2f}s",
    }
    return summary, table_per_forward


# 6) Tablas: Coldkey global y Coldkey/Web/Use-case
def load_coldkey_tables():
    if not COLDKEY_SNAPSHOT.exists():
        return "(no existe coldkey_web_usecase_stats.json)", "(no existe coldkey_web_usecase_stats.json)"
    try:
        data = json.loads(COLDKEY_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return "(error leyendo snapshot)", "(error leyendo snapshot)"

    stats = data.get("stats", {})
    agg_by_ck = defaultdict(lambda: {"tasks": 0, "succ": 0, "dur": 0.0, "hotkeys": set()})
    rows_cwu = []

    for ck, webs in stats.items():
        for web, ucs in webs.items():
            for uc, blk in ucs.items():
                tasks = safe_int(blk.get("tasks", 0))
                succ = safe_int(blk.get("successes", 0))
                dur = safe_float(blk.get("duration_sum", 0.0))
                hotk = set(blk.get("hotkeys", []))
                rate = (succ / tasks * 100) if tasks else 0.0
                avgd = (dur / tasks) if tasks else 0.0
                rows_cwu.append([ck, web, uc, len(hotk), tasks, succ, f"{rate:.1f}%", f"{avgd:.2f}"])
                agg_by_ck[ck]["tasks"] += tasks
                agg_by_ck[ck]["succ"] += succ
                agg_by_ck[ck]["dur"] += dur
                agg_by_ck[ck]["hotkeys"] |= hotk

    rows_global = []
    for ck, a in sorted(agg_by_ck.items()):
        tasks = a["tasks"]
        succ = a["succ"]
        rate = (succ / tasks * 100) if tasks else 0.0
        avgd = (a["dur"] / tasks) if tasks else 0.0
        rows_global.append([ck, len(a["hotkeys"]), tasks, succ, f"{rate:.1f}%", f"{avgd:.2f}"])

    table_global = render_table(["Coldkey", "Hotk", "Tasks", "Succ", "Rate %", "Avg s"], rows_global)
    table_cwu = render_table(["Coldkey", "Web", "Use-case", "Hotk", "Tasks", "Succ", "Rate %", "Avg s"], rows_cwu)
    return table_global, table_cwu


# 7) envío
def send_email(cfg, subject, body):
    if not cfg["to_emails"]:
        print("⚠️  SMTP_TO vacío. No hay destinatarios.")
        return
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["from_email"]
    msg["To"] = ", ".join(cfg["to_emails"])

    use_ssl = (cfg["smtp_port"] == 465) and (not cfg["starttls"])
    if use_ssl:
        import smtplib

        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"]) as server:
            if cfg["smtp_user"] and cfg["smtp_pass"]:
                server.login(cfg["smtp_user"], cfg["smtp_pass"])
            server.sendmail(cfg["from_email"], cfg["to_emails"], msg.as_string())
    else:
        import smtplib

        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            if cfg["starttls"]:
                server.starttls()
            if cfg["smtp_user"] and cfg["smtp_pass"]:
                server.login(cfg["smtp_user"], cfg["smtp_pass"])
            server.sendmail(cfg["from_email"], cfg["to_emails"], msg.as_string())


def main():
    cfg = load_cfg()
    host = socket.gethostname()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    fwd_summary, fwd_table = load_forward_totals()
    table_global, table_cwu = load_coldkey_tables()

    body_parts = [
        f"Autoppia Web Agents – Reporte {now} ({host})",
        "",
        "== Forward Totals ==",
        json.dumps(fwd_summary, ensure_ascii=False, indent=2),
        "",
        fwd_table,
        "",
        "== Coldkey Global ==",
        table_global,
        "",
        "== Coldkey / Web / Use-case ==",
        table_cwu,
        "",
    ]
    subject = f"[Autoppia] Reporte horario – {now}"
    send_email(cfg, subject, "\n".join(body_parts))
    print("✅ Email enviado.")


if __name__ == "__main__":
    main()


# pm2 start "python3 send_reports.py" --name autoppia-send-reports --cron "0 * * * *" --no-autorestart
