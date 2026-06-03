#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace


def _ensure_local_iwa_importable() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    iwa_repo = repo_root.parent / "autoppia_iwa"
    if iwa_repo.exists():
        sys.path.insert(0, str(iwa_repo))


_ensure_local_iwa_importable()

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("VALIDATOR_NAME", "dummy-smoke-validator")
os.environ.setdefault("VALIDATOR_IMAGE", "dummy-smoke-validator")

from autoppia_iwa.src.data_generation.tasks.classes import Task
from autoppia_iwa.src.demo_webs.classes import WebProject

import autoppia_web_agents_subnet.validator.evaluation.trajectory_eval as trajectory_eval


class DummyHarvesterHandler(BaseHTTPRequestHandler):
    server_version = "DummyHarvester/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"status": "ok"})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/find_trayectory":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length) or b"{}")
        target_url = payload.get("url") or "https://example.com"
        task_id = payload.get("id") or "dummy-task"

        self._send_json(
            {
                "task_id": task_id,
                "web_agent_id": "dummy-harvester",
                "trajectory": [
                    {"name": "navigate", "arguments": {"url": target_url}},
                    {"name": "done", "arguments": {"summary": "dummy trajectory complete"}},
                ],
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "model_used": "dummy",
            }
        )

    def _send_json(self, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class SmokeEvaluator:
    def __init__(self, *, web_project: WebProject, config: object):
        self.web_project = web_project
        self.config = config

    async def evaluate_single_task_solution(self, task: Task, solution: object) -> SimpleNamespace:
        actions = list(getattr(solution, "actions", []) or [])
        if len(actions) != 2:
            raise AssertionError(f"expected 2 replay actions, got {len(actions)}")
        if actions[0].__class__.__name__ != "NavigateAction":
            raise AssertionError(f"first replay action must be NavigateAction, got {actions[0].__class__.__name__}")
        if actions[-1].__class__.__name__ != "DoneAction":
            raise AssertionError(f"last replay action must be DoneAction, got {actions[-1].__class__.__name__}")
        return SimpleNamespace(raw_score=1.0, final_score=1.0, execution_history=["dummy replay ok"], gif_recording="")


async def _run() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), DummyHarvesterHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    original_evaluator = trajectory_eval.ConcurrentEvaluator
    trajectory_eval.ConcurrentEvaluator = SmokeEvaluator
    try:
        task = Task(
            id="dummy-smoke-task",
            url="http://84.247.180.192:8000/?seed=1",
            prompt="Open the page and finish.",
            web_project_id="dummy-smoke",
        )
        project = WebProject(
            id="dummy-smoke",
            name="Dummy Smoke",
            backend_url="http://127.0.0.1:1",
            frontend_url="http://84.247.180.192:8000",
        )
        score, elapsed, solution = await trajectory_eval.evaluate_trajectory(
            task=task,
            project=project,
            uid=999,
            base_url=base_url,
            max_tools=12,
        )
    finally:
        trajectory_eval.ConcurrentEvaluator = original_evaluator
        server.shutdown()
        thread.join(timeout=2.0)

    if score != 1.0:
        raise SystemExit(f"dummy harvester smoke failed: score={score} elapsed={elapsed:.2f}s tools={len(solution.actions)}")
    print(f"dummy harvester smoke passed: score=1.0 elapsed={elapsed:.2f}s tools={len(solution.actions)}")


def main() -> None:
    start = time.monotonic()
    asyncio.run(_run())
    print(f"total={time.monotonic() - start:.2f}s")


if __name__ == "__main__":
    main()
