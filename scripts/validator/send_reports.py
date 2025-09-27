#!/usr/bin/env python3
import os, json, smtplib, socket
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from html_report_template import render_html_report

# 1) .env
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

# 2) Paths
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "forward_reports"))
FORWARD_JSONL = REPORTS_DIR / "forward_summary.jsonl"
COLDKEY_SNAPSHOT = Path("coldkey_web_usecase_stats.json")


# 3) Config SMTP
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


# Utils
def safe_int(x, d=0):
    try:
        return int(x)
    except:
        return d


def safe_float(x, d=0.0):
    try:
        return float(x)
    except:
        return d


def pct(n, d):
    return (n / d * 100) if d else 0.0


# ---------- Forward Totals ----------
def load_forward_totals():
    totals = {"forwards": 0, "tasks_sent": 0, "miner_successes": 0, "miner_attempts": 0, "forward_time_sum": 0.0}
    per_rows = []
    if FORWARD_JSONL.exists():
        for line in FORWARD_JSONL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except:
                continue
            lf = rec.get("last_forward", {})
            fid = safe_int(lf.get("forward_id", -1))
            ts = safe_int(lf.get("tasks_sent", 0))
            ft = safe_float(lf.get("forward_time", 0.0))
            ms = safe_int(lf.get("miner_successes", 0))
            ma = safe_int(lf.get("miner_attempts", 0))
            totals["forwards"] += 1
            totals["tasks_sent"] += ts
            totals["miner_successes"] += ms
            totals["miner_attempts"] += ma
            totals["forward_time_sum"] += ft
            per_rows.append([fid, ts, ms, ma, f"{pct(ms,ma):.1f}%", f"{(ft/ts if ts else 0):.2f}s", f"{ft:.2f}s"])
    headers = ["Forward", "Tasks", "Successes", "Attempts", "Miner%", "Avg/task", "Forward Time"]
    total_row = [
        "TOTAL",
        totals["tasks_sent"],
        totals["miner_successes"],
        totals["miner_attempts"],
        f"{pct(totals['miner_successes'],totals['miner_attempts']):.1f}%",
        f"{(totals['forward_time_sum']/totals['tasks_sent'] if totals['tasks_sent'] else 0):.2f}s",
        f"{(totals['forward_time_sum']/totals['forwards'] if totals['forwards'] else 0):.2f}s",
    ]
    return (headers, per_rows + [total_row])


# ---------- Coldkey tables ----------
def load_coldkey_tables():
    if not COLDKEY_SNAPSHOT.exists():
        return (
            ["Coldkey", "Hotk", "Tasks", "Succ", "Rate %", "Avg s", "Avg Reward", "Avg Actions"],
            [],
        ), (
            ["Coldkey", "Web", "Use-case", "Hotk", "Tasks", "Succ", "Rate %", "Avg s", "Avg Actions"],
            [],
        )
    try:
        data = json.loads(COLDKEY_SNAPSHOT.read_text(encoding="utf-8"))
    except:
        return (
            ["Coldkey", "Hotk", "Tasks", "Succ", "Rate %", "Avg s", "Avg Reward", "Avg Actions"],
            [],
        ), (
            ["Coldkey", "Web", "Use-case", "Hotk", "Tasks", "Succ", "Rate %", "Avg s", "Avg Actions"],
            [],
        )
    stats = data.get("stats", {})
    agg = defaultdict(lambda: {"tasks": 0, "succ": 0, "dur": 0.0, "reward": 0.0, "actions": 0, "hotkeys": set()})
    rows_cwu = []
    rows_global = []
    for ck, webs in stats.items():
        for web, ucs in webs.items():
            for uc, blk in ucs.items():
                t = safe_int(blk.get("tasks", 0))
                s = safe_int(blk.get("successes", 0))
                d = safe_float(blk.get("duration_sum", 0.0))
                r = safe_float(blk.get("reward_sum", 0.0))
                a_sum = safe_int(blk.get("actions_sum", 0))
                hk = set(blk.get("hotkeys", []))
                rows_cwu.append([ck, web, uc, len(hk), t, s, f"{pct(s,t):.1f}%", f"{(d/t if t else 0):.2f}", f"{(a_sum/t if t else 0):.1f}"])
                agg[ck]["tasks"] += t
                agg[ck]["succ"] += s
                agg[ck]["dur"] += d
                agg[ck]["reward"] += r
                agg[ck]["actions"] += a_sum
                agg[ck]["hotkeys"] |= hk
    for ck, a in sorted(agg.items()):
        rows_global.append(
            [
                ck,
                len(a["hotkeys"]),
                a["tasks"],
                a["succ"],
                f"{pct(a['succ'],a['tasks']):.1f}%",
                f"{(a['dur']/a['tasks'] if a['tasks'] else 0):.2f}",
                f"{(a['reward']/a['tasks'] if a['tasks'] else 0):.2f}",
                f"{(a['actions']/a['tasks'] if a['tasks'] else 0):.1f}",
            ]
        )
    return (
        ["Coldkey", "Hotk", "Tasks", "Succ", "Rate %", "Avg s", "Avg Reward", "Avg Actions"],
        rows_global,
    ), (
        ["Coldkey", "Web", "Use-case", "Hotk", "Tasks", "Succ", "Rate %", "Avg s", "Avg Actions"],
        rows_cwu,
    )


# ---------- Tareas del último forward ----------
def load_last_forward_tasks():
    if not FORWARD_JSONL.exists():
        return (["Web", "Use-case", "Prompt"], [])
    try:
        last = json.loads(FORWARD_JSONL.read_text(encoding="utf-8").splitlines()[-1])
    except Exception:
        return (["Web", "Use-case", "Prompt"], [])

    # Buscar tasks dentro de last_forward (nuevo formato) o a nivel raíz (legacy)
    tasks = last.get("tasks", []) or last.get("last_forward", {}).get("tasks", [])

    rows = [[t.get("web_project", ""), t.get("use_case", ""), t.get("prompt", "")] for t in tasks]
    return (["Web", "Use-case", "Prompt"], rows)


# ---------- Resumen global de tareas ----------
def summarize_task_types():
    if not FORWARD_JSONL.exists():
        return (["Web", "Use-case", "Tasks Sent"], [])
    counts = Counter()
    for line in FORWARD_JSONL.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except:
            continue
        # mirar tasks en root o dentro de last_forward
        all_tasks = rec.get("tasks", []) or rec.get("last_forward", {}).get("tasks", [])
        for t in all_tasks:
            counts[(t.get("web_project", ""), t.get("use_case", ""))] += 1
    rows = [[w, uc, c] for (w, uc), c in counts.items()]
    return (["Web", "Use-case", "Tasks Sent"], rows)


# ---------- Envío ----------
def send_email(cfg, subject, body_html, body_text=""):
    if not cfg["to_emails"]:
        print("⚠️  SMTP_TO vacío. No hay destinatarios.")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_email"]
    msg["To"] = ", ".join(cfg["to_emails"])
    msg.attach(MIMEText(body_text or "Reporte en HTML adjunto.", "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    use_ssl = (cfg["smtp_port"] == 465) and (not cfg["starttls"])
    if use_ssl:
        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"]) as server:
            if cfg["smtp_user"] and cfg["smtp_pass"]:
                server.login(cfg["smtp_user"], cfg["smtp_pass"])
            server.sendmail(cfg["from_email"], cfg["to_emails"], msg.as_string())
    else:
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

    fwd_table_data = load_forward_totals()
    table_global_data, table_cwu_data = load_coldkey_tables()
    task_table_data = load_last_forward_tasks()
    task_summary_data = summarize_task_types()

    body_html = render_html_report(
        fwd_table_data,
        table_global_data,
        table_cwu_data,
        task_table_data,
        task_summary_data,
        host,
        now,
    )
    body_text = f"Autoppia Web Agents Report – {now}\nVer versión HTML."
    subject = f"[Autoppia] Reporte horario – {now}"
    send_email(cfg, subject, body_html, body_text)
    print("✅ Email enviado.")


if __name__ == "__main__":
    main()
