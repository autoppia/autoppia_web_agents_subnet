#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import bittensor as bt

from autoppia_web_agents_subnet.opensource.utils_git import (
    normalize_and_validate_github_url,
    resolve_remote_ref_commit,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run validator-like sandbox evaluation for a miner GitHub URL.",
    )
    parser.add_argument("--github", required=True, help="GitHub URL submitted by miner (must include explicit ref/commit).")
    parser.add_argument("--tasks", type=int, default=3, help="Number of tasks to evaluate (generated mode only).")
    parser.add_argument("--tasks-json", type=str, default="", help="Path to season task JSON file. If set, tasks are loaded from this file.")
    parser.add_argument("--max-steps", type=int, default=12, help="Max action steps per task.")
    parser.add_argument("--uid", type=int, default=99999, help="Synthetic UID used for sandboxed run.")
    parser.add_argument("--output-json", type=str, default="", help="Optional output report path.")
    parser.add_argument("--env-file", type=str, default=".env", help="Optional env file to load before evaluation (default: .env).")
    parser.add_argument("--keep-containers", action="store_true", help="Preserve sandbox containers for debugging.")
    parser.add_argument("--keep-gateway", action="store_true", help="Preserve gateway container after run.")
    return parser.parse_args()


def _require_gateway_keys() -> None:
    allowed = (os.getenv("GATEWAY_ALLOWED_PROVIDERS") or "").strip().lower()
    providers = [p.strip() for p in allowed.split(",") if p.strip()] if allowed else ["openai", "chutes"]

    missing: list[str] = []
    if "openai" in providers and not (os.getenv("OPENAI_API_KEY") or "").strip():
        missing.append("OPENAI_API_KEY")
    if "chutes" in providers and not (os.getenv("CHUTES_API_KEY") or "").strip():
        missing.append("CHUTES_API_KEY")

    if missing:
        raise RuntimeError(f"Missing required API key env vars: {', '.join(missing)}")


def _validate_github_url(raw_github_url: str) -> tuple[str, str | None]:
    validated = normalize_and_validate_github_url(
        raw_github_url,
        miner_uid=None,
        require_ref=True,
    )
    normalized_url, ref = validated if isinstance(validated, tuple) else (validated, None)
    if not normalized_url:
        raise RuntimeError(f"Invalid GitHub URL: {raw_github_url}")

    raw_s = str(raw_github_url or "")
    is_commit_url = "/commit/" in raw_s
    if is_commit_url:
        if resolve_remote_ref_commit(str(normalized_url), "HEAD") is None:
            raise RuntimeError("git ls-remote failed (repo unreachable)")
    else:
        if not ref:
            raise RuntimeError("GitHub URL must include explicit ref (branch/tag/commit)")
        if resolve_remote_ref_commit(str(normalized_url), str(ref)) is None:
            raise RuntimeError(f"git ls-remote failed for ref '{ref}'")
    return str(normalized_url), ref


def _load_env_file(path: str) -> None:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        if not key:
            continue
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def _load_tasks_from_json(path: Path, limit: int) -> list[Any]:
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    from autoppia_iwa.src.demo_webs.config import demo_web_projects
    from autoppia_web_agents_subnet.validator.models import TaskWithProject

    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict):
        rows = payload.get("tasks")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise RuntimeError(f"Invalid tasks file format (expected list in 'tasks'): {path}")

    projects_map = {project.name: project for project in demo_web_projects}
    out: list[TaskWithProject] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        project_name = row.get("project_name")
        task_data = row.get("task")
        if not isinstance(project_name, str) or not isinstance(task_data, dict):
            continue
        project = projects_map.get(project_name)
        if project is None:
            continue
        task = Task.deserialize(task_data)
        out.append(TaskWithProject(project=project, task=task))
        if len(out) >= limit:
            break

    if not out:
        raise RuntimeError(f"No usable tasks found in JSON: {path}")
    return out


async def _get_tasks(*, tasks_json: str, tasks: int) -> list[Any]:
    from autoppia_web_agents_subnet.validator.evaluation.tasks import generate_tasks

    count = max(1, int(tasks))
    if tasks_json:
        return _load_tasks_from_json(Path(tasks_json), limit=count)
    generated = await generate_tasks(count)
    if not generated:
        raise RuntimeError("Task generation returned no tasks")
    return generated[:count]


async def _run() -> int:
    args = _parse_args()
    bt.logging.set_info(True)

    _load_env_file(args.env_file)

    if args.keep_containers:
        os.environ["SANDBOX_KEEP_AGENT_CONTAINERS"] = "true"

    # Validator modules validate these on import; set harmless defaults for miner-local eval.
    os.environ.setdefault("VALIDATOR_NAME", "miner-local-eval")
    os.environ.setdefault("VALIDATOR_IMAGE", "miner-local-eval")

    _require_gateway_keys()
    normalized_url, ref = _validate_github_url(args.github)
    bt.logging.info(f"Validated GitHub URL: {normalized_url} ref={ref}")

    from autoppia_web_agents_subnet.opensource.sandbox_manager import SandboxManager
    from autoppia_web_agents_subnet.opensource.utils_docker import stop_and_remove
    from autoppia_web_agents_subnet.validator import config as validator_config
    from autoppia_web_agents_subnet.validator.evaluation.rewards import calculate_reward_for_task
    from autoppia_web_agents_subnet.validator.evaluation.stateful_cua_eval import evaluate_with_stateful_cua

    manager = SandboxManager()
    report: dict[str, Any] = {
        "github_input": args.github,
        "normalized_repo": normalized_url,
        "ref": ref,
        "uid": int(args.uid),
        "started_at": time.time(),
        "tasks": [],
    }

    agent = None
    gateway_container = None
    try:
        manager.deploy_gateway()
        gateway_container = getattr(manager, "gateway_container", None)
        bt.logging.info("Gateway ready")

        agent = manager.deploy_agent(int(args.uid), args.github)
        if agent is None:
            raise RuntimeError(
                "Sandbox agent deployment failed. Ensure repo starts an API with /health and /act, "
                "and includes required runtime deps. Re-run with --keep-containers to inspect docker logs."
            )
        bt.logging.info(f"Agent deployed at {agent.base_url}")

        task_items = await _get_tasks(tasks_json=args.tasks_json, tasks=args.tasks)
        task_ids = [str(getattr(item.task, "id", "")) for item in task_items]
        manager.set_allowed_task_ids(task_ids=task_ids)

        total_tasks = len(task_items)
        max_cost_per_task = float(getattr(validator_config, "MAX_TASK_DOLLAR_COST_USD", 0.0) or 0.0)
        cost_limit_exceed_count = int(
            getattr(
                validator_config,
                "MAX_OVER_COST_TASKS_BEFORE_FORCED_ZERO_SCORE",
                0,
            )
            or 0
        )
        cost_limit_hits = 0
        stop_for_cost_limit_streak = False
        total_reward = 0.0
        solved = 0
        for idx, item in enumerate(task_items, start=1):
            score, exec_time, _task_solution = await evaluate_with_stateful_cua(
                task=item.task,
                uid=int(args.uid),
                base_url=agent.base_url,
                max_steps=max(1, int(args.max_steps)),
            )
            usage = manager.get_usage_for_task(task_id=item.task.id) or {}
            try:
                cost = float(usage.get("total_cost", 0.0) or 0.0)
            except Exception:
                cost = 0.0
            try:
                tokens = int(usage.get("total_tokens", 0) or 0)
            except Exception:
                tokens = 0

            reward = float(
                calculate_reward_for_task(
                    eval_score=float(score),
                    execution_time=float(exec_time),
                    token_cost=cost,
                )
            )
            total_reward += reward
            if float(score) >= 1.0:
                solved += 1

            if cost_limit_exceed_count > 0 and max_cost_per_task > 0.0 and cost >= max_cost_per_task - 1e-12:
                cost_limit_hits += 1

            row = {
                "idx": idx,
                "task_id": str(item.task.id),
                "project": str(item.project.name),
                "score": float(score),
                "execution_time_s": float(exec_time),
                "cost_usd": cost,
                "tokens": tokens,
                "reward": reward,
                "over_cost_limit": bool(max_cost_per_task > 0.0 and cost >= max_cost_per_task - 1e-12),
            }
            report["tasks"].append(row)
            bt.logging.info(
                f"[{idx}/{len(task_items)}] task={row['task_id']} score={row['score']:.3f} "
                f"time={row['execution_time_s']:.2f}s cost=${row['cost_usd']:.4f} "
                f"tokens={row['tokens']} reward={row['reward']:.3f}"
            )
            if cost_limit_exceed_count > 0 and max_cost_per_task > 0.0 and row["over_cost_limit"]:
                bt.logging.warning(
                    f"Cost limit hit {cost_limit_hits}/{cost_limit_exceed_count} on task {idx}: "
                    f"${cost:.4f} >= ${max_cost_per_task:.4f}"
                )
                if cost_limit_hits >= cost_limit_exceed_count:
                    stop_for_cost_limit_streak = True
                    bt.logging.warning(
                        "Reached MAX_OVER_COST_TASKS_BEFORE_FORCED_ZERO_SCORE; "
                        "stopping remaining tasks and forcing validator score to 0."
                    )
                    break

        n_requested = max(total_tasks, 1)
        n_evaluated = max(len(report["tasks"]), 1)
        validator_final_score = 0.0 if stop_for_cost_limit_streak else (total_reward / float(n_requested))
        report["summary"] = {
            "task_count_requested": total_tasks,
            "task_count_evaluated": len(report["tasks"]),
            "solved_count": solved,
            "avg_score_over_requested": sum(float(t["score"]) for t in report["tasks"]) / n_requested,
            "avg_score_over_evaluated": sum(float(t["score"]) for t in report["tasks"]) / n_evaluated,
            "avg_reward_over_requested": total_reward / n_requested,
            "avg_reward_over_evaluated": total_reward / n_evaluated,
            "validator_final_score": validator_final_score,
            "total_reward": total_reward,
            "total_cost_usd": sum(float(t["cost_usd"]) for t in report["tasks"]),
            "total_tokens": sum(int(t["tokens"]) for t in report["tasks"]),
            "duration_s": max(time.time() - float(report["started_at"]), 0.0),
            "max_task_cost_usd": max_cost_per_task,
            "max_over_cost_tasks_before_forced_zero_score": cost_limit_exceed_count,
            "over_cost_task_hits": cost_limit_hits,
            "forced_zero_score": stop_for_cost_limit_streak,
        }

        summary = report["summary"]
        bt.logging.info(
            f"Done | tasks={summary['task_count_evaluated']}/{summary['task_count_requested']} "
            f"solved={summary['solved_count']} validator_score={summary['validator_final_score']:.3f} "
            f"avg_reward_req={summary['avg_reward_over_requested']:.3f} "
            f"cost=${summary['total_cost_usd']:.4f} tokens={summary['total_tokens']} "
            f"forced_zero={summary['forced_zero_score']}"
        )

        if args.output_json:
            out_path = Path(args.output_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, sort_keys=True)
            bt.logging.info(f"Report written to {out_path}")
        else:
            print(json.dumps(report, indent=2, sort_keys=True))

        return 0
    finally:
        try:
            if agent is not None:
                manager.cleanup_agent(int(args.uid))
        except Exception:
            pass
        try:
            manager.cleanup_all_agents()
        except Exception:
            pass
        if not args.keep_gateway and gateway_container is not None:
            try:
                stop_and_remove(gateway_container)
            except Exception:
                pass


def main() -> int:
    try:
        return asyncio.run(_run())
    except Exception as exc:
        bt.logging.error(f"Miner eval failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
