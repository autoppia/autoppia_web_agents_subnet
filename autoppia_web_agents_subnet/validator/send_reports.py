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
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
FORWARD_JSONL = REPORTS_DIR / "forward_summary.jsonl"  # ahora lee desde REPORTS_DIR
COLDKEY_SNAPSHOT = Path("coldkey_web_usecase_stats.json")


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


def pct(numer, denom):
    return (numer / denom * 100.0) if denom else 0.0


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


# ---------- Normalizador de líneas: soporta formato nuevo y legado ----------
def _normalize_line(rec: dict):
    """
    Devuelve una tupla normalizada con los campos por-forward:
      (forward_id, tasks_sent, forward_time, miner_successes, miner_attempts,
       avg_response_time, avg_time_per_task, miner_success_percentage)

    y además un dict (lf, tot) si venía en formato nuevo.
    """
    if "last_forward" in rec or "totals" in rec:
        lf = rec.get("last_forward", {}) or rec.get("forward", {})  # por si alguien guardó "forward"
        tot = rec.get("totals", {})

        fid = safe_int(lf.get("forward_id", -1), -1)
        tasks_sent = safe_int(lf.get("tasks_sent", 0))
        fwd_time = safe_float(lf.get("forward_time", 0.0))
        miner_succ = safe_int(lf.get("miner_successes", 0))
        miner_atts = safe_int(lf.get("miner_attempts", 0))
        avg_resp = None  # este campo no viene de serie en lf

        avg_per_task = (fwd_time / tasks_sent) if tasks_sent else 0.0
        miner_pct = pct(miner_succ, miner_atts)
        return (fid, tasks_sent, fwd_time, miner_succ, miner_atts, avg_resp, avg_per_task, miner_pct), (lf, tot)
    else:
        # legacy flat
        fid = safe_int(rec.get("forward_id", -1), -1)
        tasks_sent = safe_int(rec.get("tasks_sent", 0))
        fwd_time = safe_float(rec.get("forward_time", 0.0))
        miner_succ = safe_int(rec.get("miner_successes", 0))
        miner_atts = safe_int(rec.get("miner_attempts", 0))
        avg_resp = rec.get("avg_response_time", None)
        avg_resp = safe_float(avg_resp, 0.0) if avg_resp is not None else None

        avg_per_task = (fwd_time / tasks_sent) if tasks_sent else 0.0
        miner_pct = pct(miner_succ, miner_atts)
        return (fid, tasks_sent, fwd_time, miner_succ, miner_atts, avg_resp, avg_per_task, miner_pct), (None, None)


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
                raw = json.loads(line)
            except Exception:
                continue

            norm, blocks = _normalize_line(raw)
            (fid, tasks_sent, fwd_time, miner_succ, miner_atts, avg_resp, avg_per_task, miner_pct) = norm

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
                    fid if fid != -1 else "-",
                    tasks_sent,
                    miner_succ,
                    miner_atts,
                    f"{miner_pct:.1f}%",
                    f"{avg_per_task:.2f}s",
                    f"{fwd_time:.2f}s",
                ]
            )

    # Agregados
    miner_success_rate = pct(totals["miner_successes"], totals["miner_attempts"])
    avg_forward_time = (totals["forward_time_sum"] / totals["forwards"]) if totals["forwards"] else 0.0
    avg_response_time = (totals["avg_response_time_sum"] / totals["avg_response_time_count"]) if totals["avg_response_time_count"] else 0.0
    avg_time_per_task_overall = (totals["forward_time_sum"] / totals["tasks_sent"]) if totals["tasks_sent"] else 0.0

    headers = ["Forward", "Tasks", "Successes", "Attempts", "Miner%", "Avg/task", "Forward Time"]
    # Añadimos un TOTAL sintetizado al final
    total_row = [
        "TOTAL",
        totals["tasks_sent"],
        totals["miner_successes"],
        totals["miner_attempts"],
        f"{miner_success_rate:.1f}%",
        f"{avg_time_per_task_overall:.2f}s",
        f"{avg_forward_time:.2f}s",
    ]
    table_per_forward = render_table(headers, per_forward_rows + ([total_row] if per_forward_rows else []))

    summary = {
        "total_forwards": totals["forwards"],
        "total_tasks_sent": totals["tasks_sent"],
        # NUEVO: promedio global por task (total_time / tasks_total)
        "avg_time_per_task_overall": f"{avg_time_per_task_overall:.2f}s",
        # NUEVO: porcentaje global de éxito de miners
        "miner_percentage": f"{miner_success_rate:.1f}%",
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
