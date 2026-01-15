from __future__ import annotations

import time
from typing import Tuple

import bittensor as bt

from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.evaluation.stateful_evaluator import AsyncStatefulEvaluator, ScoreDetails
from autoppia_iwa.src.web_agents.cua import ApifiedWebCUA
from autoppia_iwa.src.web_agents.classes import TaskSolution


async def evaluate_with_stateful_cua(
    *,
    task: Task,
    uid: int,
    base_url: str,
    max_steps: int = 30,
) -> Tuple[float, float, TaskSolution]:
    """
    Evaluate a sandboxed miner agent using AsyncStatefulEvaluator + ApifiedWebCUA.
    """
    agent = ApifiedWebCUA(base_url=base_url, name=f"miner-{uid}", id=str(uid))
    evaluator = AsyncStatefulEvaluator(task=task, web_agent_id=str(uid))

    start_ts = time.time()
    final_score: ScoreDetails = ScoreDetails()

    try:
        step_index = 0
        step_result = await evaluator.reset()
        final_score = step_result.score

        while step_index < max_steps and not bool(final_score.success):
            snapshot = step_result.snapshot
            html = snapshot.html or ""
            current_url = snapshot.url or task.url

            try:
                actions = await agent.act(
                    task=task,
                    snapshot_html=html,
                    url=current_url,
                    step_index=step_index,
                )
            except Exception as exc:
                bt.logging.warning(f"[stateful_cua_eval] miner {uid} /act failed: {exc}")
                actions = []

            # Single-step semantics: execute at most one action per loop.
            if actions:
                action = actions[0]
                step_result = await evaluator.step(action)
            else:
                step_result = await evaluator.step(None)

            final_score = step_result.score
            step_index += 1

    except Exception as exc:
        bt.logging.error(f"[stateful_cua_eval] miner {uid} evaluation error: {exc}")
        final_score = ScoreDetails()
    finally:
        # Snapshot minimal solution from the evaluator history for similarity penalties.
        try:
            history = list(getattr(evaluator, "history", []) or [])
            actions = []
            for h in history:
                try:
                    a = getattr(h, "action", None)
                    if a is not None:
                        actions.append(a)
                except Exception:
                    continue
            solution = TaskSolution(
                task_id=str(getattr(task, "id", "")),
                actions=actions,
                web_agent_id=str(uid),
            )
        except Exception:
            # If we cannot reconstruct a solution, append a minimal empty one
            solution = TaskSolution(task_id=str(getattr(task, "id", "")), actions=[], web_agent_id=str(uid))

        try:
            await evaluator.close()
        except Exception:
            pass
    
    score = max(0.0, min(final_score.raw_score, 1.0))
    elapsed = max(time.time() - start_ts, 0.0)
    return score, elapsed, solution


__all__ = ["evaluate_with_stateful_cua"]
