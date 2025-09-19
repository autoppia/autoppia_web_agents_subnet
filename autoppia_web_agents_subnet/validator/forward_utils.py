# autoppia_web_agents_subnet/validator/forward_utils.py
from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from typing import Any, Dict, Iterable, List, Set, Tuple
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
import bittensor as bt
from filelock import FileLock

from autoppia_iwa.src.data_generation.domain.classes import Task, TaskGenerationConfig
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.web_agents.classes import TaskSolution

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    SetOperatorEndpointSynapse,
)
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.utils.uids import get_random_uids

from autoppia_web_agents_subnet.validator.config import (
    CHECK_VERSION_PROBABILITY,
    CHECK_VERSION_SYNAPSE,
    EFFICIENCY_WEIGHT,
    FEEDBACK_TIMEOUT,
    MAX_ACTIONS_LENGTH,
    MIN_RESPONSE_REWARD,
    MIN_SCORE_FOR_CORRECT_FORMAT,
    SAMPLE_SIZE,
    TASK_SLEEP,
    TIMEOUT,
    SUCCESS_THRESHOLD,
    TIME_WEIGHT,
)
from autoppia_web_agents_subnet.validator.leaderboard import (
    LeaderboardTaskRecord,
    send_many_tasks_to_leaderboard_async,
)
from autoppia_web_agents_subnet.validator.reward import get_rewards_with_details
from autoppia_web_agents_subnet.validator.stats import (
    update_coldkey_stats_json,
)
from autoppia_web_agents_subnet.validator.visualization import (
    print_leaderboard_table,
    print_coldkey_resume,
)
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_web_agents_subnet.validator.version import (
    check_miner_not_responding_to_invalid_version,
)


# ─────────────────────────────────────────────────────────────────────────────
# Task list helpers
# ─────────────────────────────────────────────────────────────────────────────
def interleave_tasks(*lists: List[Any]) -> Iterable[Any]:
    """
    Interleave multiple lists: [a1, a2], [b1, b2] -> a1, b1, a2, b2 (skips None).
    """
    return (item for group in itertools.zip_longest(*lists) for item in group if item is not None)


def split_tasks_evenly(total_tasks: int, num_projects: int) -> List[int]:
    """
    Evenly distribute `total_tasks` across `num_projects`.
    Remainder is assigned one-by-one from the end. Example: total=10, projects=3 -> [3, 3, 4]
    """
    base = total_tasks // num_projects
    extra = total_tasks % num_projects
    distribution = [base] * num_projects
    for i in range(1, extra + 1):
        distribution[-i] += 1
    return distribution


# ─────────────────────────────────────────────────────────────────────────────
# Task generation
# ─────────────────────────────────────────────────────────────────────────────
async def generate_tasks_limited_use_cases(
    project: WebProject,
    total_tasks: int,
    prompts_per_use_case: int,
    num_use_cases: int,
) -> List[Task]:
    """
    Generate up to `total_tasks` tasks for `project` sampling `num_use_cases` use cases.
    """
    config = TaskGenerationConfig(
        prompts_per_use_case=prompts_per_use_case,
        generate_global_tasks=True,
        final_task_limit=total_tasks,
        num_use_cases=num_use_cases,
    )
    pipeline = TaskGenerationPipeline(web_project=project, config=config)
    return await pipeline.generate()


# ─────────────────────────────────────────────────────────────────────────────
# Responses → solutions + times
# ─────────────────────────────────────────────────────────────────────────────
def get_task_solution_from_synapse(
    task_id: str,
    synapse: TaskSynapse,
    web_agent_id: str,
    max_actions_length: int = MAX_ACTIONS_LENGTH,
) -> TaskSolution:
    """
    Safely extract actions from a TaskSynapse response and limit their length.
    NOTE: correct slicing is [:max], not [max].
    """
    actions = []
    if synapse and hasattr(synapse, "actions") and isinstance(synapse.actions, list):
        actions = synapse.actions[:max_actions_length]
    return TaskSolution(task_id=task_id, actions=actions, web_agent_id=web_agent_id)


def collect_task_solutions(
    task: Task,
    responses: List[TaskSynapse],
    miner_uids: List[int],
) -> Tuple[List[TaskSolution], List[float]]:
    """
    Convert miner responses into TaskSolution and gather process times.
    """
    task_solutions: List[TaskSolution] = []
    execution_times: List[float] = []

    for miner_uid, response in zip(miner_uids, responses):
        try:
            task_solutions.append(
                get_task_solution_from_synapse(
                    task_id=task.id,
                    synapse=response,
                    web_agent_id=str(miner_uid),
                )
            )
        except Exception as e:
            bt.logging.error(f"Miner response format error: {e}")
            task_solutions.append(TaskSolution(task_id=task.id, actions=[], web_agent_id=str(miner_uid)))

        if response and hasattr(response.dendrite, "process_time") and response.dendrite.process_time is not None:
            execution_times.append(response.dendrite.process_time)
            bt.logging.info(f"[TIME] uid={miner_uid} process_time={response.dendrite.process_time:.3f}s (taken)")

        else:
            execution_times.append(TIMEOUT)
            bt.logging.info(f"[TIME] uid={miner_uid} process_time=None -> using TIMEOUT={TIMEOUT:.3f}s")

    return task_solutions, execution_times


# ─────────────────────────────────────────────────────────────────────────────
# Synapse sending
# ─────────────────────────────────────────────────────────────────────────────
async def send_task_synapse_to_miners(validator, miner_axons, task_synapse: TaskSynapse, timeout: int) -> List[TaskSynapse]:
    """
    Send a TaskSynapse (with correct version) and return the responses.
    """
    task_synapse.version = validator.version
    responses: List[TaskSynapse] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=task_synapse,
        deserialize=True,
        timeout=timeout,
        retries=1,
    )
    bt.logging.info(f"Received responses from {len(responses)} miners.")
    return responses


async def send_feedback_synapse_to_miners(
    validator,
    miner_axons: List[bt.axon],
    miner_uids: List[int],
    task: Task,
    rewards,
    execution_times,
    task_solutions: List[TaskSolution],
    test_results_matrices: List[List[List[Any]]],
    evaluation_results: List[Dict[str, Any]],
) -> None:
    """
    Build and send a TaskFeedbackSynapse to each miner with their evaluation details.
    """
    feedback_list: List[TaskFeedbackSynapse] = []
    for i, miner_uid in enumerate(miner_uids):
        feedback_list.append(
            TaskFeedbackSynapse(
                version=__version__,
                miner_id=str(miner_uid),
                validator_id=str(validator.uid),
                task_id=task.id,
                task_url=task.url,
                prompt=task.prompt,
                score=rewards[i],
                execution_time=execution_times[i],
                tests=task.tests,
                actions=task_solutions[i].actions if i < len(task_solutions) else [],
                test_results_matrix=(test_results_matrices[i] if i < len(test_results_matrices) else None),
                evaluation_result=(evaluation_results[i] if i < len(evaluation_results) else None),
            )
        )

    ColoredLogger.info(f"Sending TaskFeedbackSynapse to {len(miner_axons)} miners in parallel", ColoredLogger.BLUE)

    tasks = [asyncio.create_task(validator.dendrite(axons=[axon], synapse=fb, deserialize=True, timeout=FEEDBACK_TIMEOUT)) for axon, fb in zip(miner_axons, feedback_list)]
    await asyncio.gather(*tasks)
    ColoredLogger.info("Feedback responses received from miners", ColoredLogger.BLUE)


# ─────────────────────────────────────────────────────────────────────────────
# Leaderboard + coldkey snapshots
# ─────────────────────────────────────────────────────────────────────────────
def _schedule_leaderboard_logging(
    validator,
    miner_uids: List[int],
    execution_times: List[float],
    task_obj: Task,
    evaluation_results: List[dict],
    task_solutions: List[TaskSolution],
    timeout: int = 300,
) -> None:
    """
    Build LeaderboardTaskRecord objects, snapshot coldkey stats,
    and dispatch async sending without blocking the main loop.
    """
    try:
        miner_hotkeys = [validator.metagraph.hotkeys[uid] for uid in miner_uids]
        miner_coldkeys = [validator.metagraph.coldkeys[uid] for uid in miner_uids]

        records: List[LeaderboardTaskRecord] = []
        for i, miner_uid in enumerate(miner_uids):
            score = float(evaluation_results[i].get("final_score", 0.0)) if i < len(evaluation_results) else 0.0
            success = score > SUCCESS_THRESHOLD  # aligns with SUCCESS_THRESHOLD = 0 in forward.py
            actions_serialized = [a.model_dump() for a in task_solutions[i].actions] if i < len(task_solutions) else []
            duration_val = float(execution_times[i]) if i < len(execution_times) else 0.0

            records.append(
                LeaderboardTaskRecord(
                    validator_uid=int(validator.uid),
                    miner_uid=int(miner_uid),
                    miner_hotkey=miner_hotkeys[i],
                    miner_coldkey=miner_coldkeys[i],
                    task_id=str(task_obj.id),
                    task_prompt=task_obj.prompt,
                    website=task_obj.url,
                    web_project=task_obj.web_project_id,
                    use_case=task_obj.use_case.name,
                    actions=actions_serialized,
                    success=success,
                    score=score,
                    duration=duration_val,
                )
            )

        print_leaderboard_table(records, task_obj.prompt, task_obj.web_project_id)
        update_coldkey_stats_json(records)
        print_coldkey_resume()

        coro = send_many_tasks_to_leaderboard_async(records, timeout=timeout)
        task = asyncio.create_task(coro)
        task.add_done_callback(
            lambda fut: ColoredLogger.info(
                "Leaderboard logs saved successfully." if not fut.exception() else f"Error sending leaderboard logs: {fut.exception()}",
                ColoredLogger.GREEN if not fut.exception() else ColoredLogger.RED,
            )
        )
        ColoredLogger.info(f"Dispatched {len(records)} leaderboard records in background.", ColoredLogger.GREEN)
    except Exception as e:
        bt.logging.error(f"Failed scheduling leaderboard send: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# All-miners evaluation (one task → rewards vector for ALL UIDs)
# ─────────────────────────────────────────────────────────────────────────────
async def evaluate_task_all_miners(
    validator,
    web_project: WebProject,
    task: Task,
) -> tuple[NDArray[np.float32], float]:
    """
    Evaluate ONE task against ALL miners and return:
      - rewards_vec: float32 vector of length metagraph.n aligned by UID
      - avg_miner_time: average process_time over miners for this task (seconds)
    """
    n = validator.metagraph.n
    miner_uids: List[int] = list(range(n))
    miner_axons = [validator.metagraph.axons[uid] for uid in miner_uids]

    task_synapse = TaskSynapse(
        prompt=task.prompt,
        url=task.url,
        html="",
        screenshot="",
        actions=[],
        version=validator.version,
    )

    # Optional version check (probabilistic)
    version_responses = await check_miner_not_responding_to_invalid_version(
        validator,
        task_synapse=TaskSynapse(**task_synapse.model_dump()),
        miner_axons=miner_axons,
        probability=CHECK_VERSION_PROBABILITY,
        timeout=CHECK_VERSION_SYNAPSE,
    )
    invalid_version_responders: Set[int] = set()
    for i, vresp in enumerate(version_responses or []):
        if vresp and hasattr(vresp, "actions") and vresp.actions:
            invalid_version_responders.add(miner_uids[i])

    ColoredLogger.info(f"Sending Task Synapse to ALL miners :{task_synapse.prompt} (URL: {task_synapse.url})", ColoredLogger.YELLOW)
    responses = await send_task_synapse_to_miners(validator, miner_axons, task_synapse, timeout=TIMEOUT)

    task_solutions, execution_times = collect_task_solutions(task, responses, miner_uids)

    rewards, test_results_matrices, evaluation_results = await get_rewards_with_details(
        validator,
        web_project=web_project,
        task=task,
        task_solutions=task_solutions,
        execution_times=execution_times,
        time_weight=TIME_WEIGHT,
        efficiency_weight=EFFICIENCY_WEIGHT,
        min_correct_format_score=MIN_SCORE_FOR_CORRECT_FORMAT,
        min_response_reward=MIN_RESPONSE_REWARD,
        invalid_version_responders=invalid_version_responders,
    )
    bt.logging.info(f"Miners final rewards: {rewards}")
    # === DEBUG: mapear reward -> uid/hotkey/coldkey y ordenar ===
    rows = []
    for i, uid in enumerate(miner_uids):
        hk = validator.metagraph.hotkeys[uid]
        ck = validator.metagraph.coldkeys[uid]
        r = float(rewards[i]) if i < len(rewards) else 0.0
        t = float(execution_times[i]) if i < len(execution_times) else 0.0
        rows.append((uid, hk, ck, r, t))

    rows.sort(key=lambda x: x[3], reverse=True)

    bt.logging.info("=== [TASK REWARDS] uid/hk/ck/reward/time (ordenado) ===")
    for uid, hk, ck, r, t in rows[:25]:  # top 25 para no saturar
        bt.logging.info(f"[REWARD] uid={uid:<3} hk={hk[:10]}… ck={ck[:10]}…  reward={r:.6f}  time={t:.2f}s")

    await send_feedback_synapse_to_miners(
        validator=validator,
        miner_axons=miner_axons,
        miner_uids=miner_uids,
        task=task,
        task_solutions=task_solutions,
        test_results_matrices=test_results_matrices,
        evaluation_results=evaluation_results,
        rewards=rewards,
        execution_times=execution_times,
    )
    _schedule_leaderboard_logging(
        validator,
        miner_uids,
        execution_times,
        task,
        evaluation_results,
        task_solutions,
    )

    rewards_vec = np.asarray(rewards, dtype=np.float32)
    if rewards_vec.shape[0] != n:
        padded = np.zeros(n, dtype=np.float32)
        padded[: min(n, rewards_vec.shape[0])] = rewards_vec[: min(n, rewards_vec.shape[0])]
        rewards_vec = padded

    avg_miner_time = float(sum(execution_times) / len(execution_times)) if execution_times else 0.0
    return rewards_vec, avg_miner_time


# ─────────────────────────────────────────────────────────────────────────────
# Operator endpoint broadcast (optional, periodic)
# ─────────────────────────────────────────────────────────────────────────────
async def broadcast_and_save_operator_endpoints(validator) -> None:
    """
    Broadcast a SetOperatorEndpointSynapse and persist responses to JSON.
    """
    operator_synapse = SetOperatorEndpointSynapse(version=__version__, endpoint="https://your-validator-endpoint.com")
    bt.logging.info("Broadcasting SetOperatorEndpointSynapse...")

    miner_uids = get_random_uids(validator, k=SAMPLE_SIZE)
    miner_axons = [validator.metagraph.axons[uid] for uid in miner_uids]

    responses: List[SetOperatorEndpointSynapse] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=operator_synapse,
        deserialize=True,
        timeout=10,
        retries=1,
    )
    bt.logging.info(f"Got {len(responses)} responses for SetOperatorEndpointSynapse")
    await save_operator_endpoints_in_json(responses, miner_uids)


async def save_operator_endpoints_in_json(
    responses: List[SetOperatorEndpointSynapse],
    miner_uids: List[int],
    filename: str = "operator_endpoints.json",
):
    """
    Save miner_uid → endpoint mapping to a JSON file (with a simple file lock).
    """
    lock_file = filename + ".lock"
    if not os.path.isfile(filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({}, f)

    with FileLock(lock_file):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if not isinstance(existing, dict):
                    existing = {}
        except json.JSONDecodeError:
            existing = {}

        for uid, resp in zip(miner_uids, responses):
            existing[str(uid)] = resp.endpoint if resp else "no_response"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4)

    bt.logging.info(f"Saved {len(responses)} endpoints to {filename}")


# ───────────────────────────────────────────────
# Helper para guardar resumen por forward
# ───────────────────────────────────────────────

import os
import json
from pathlib import Path
from collections import Counter
import bittensor as bt


def save_forward_report(summary: dict, tasks: list[dict] | None = None) -> None:
    ...

    """
    Escribe una línea JSON con ÚNICAMENTE:
      {
        "last_forward": {
            ...campos snapshot del forward...,
            "tasks": [ {web_project, use_case, prompt}, ... ],
            "task_counts_by_type": [ {web, use_case, tasks}, ... ]
        },
        "totals": {
            ...campos acumulados...,
            "task_counts_by_type": [ {web, use_case, tasks}, ... ]
        }
      }
    """
    try:
        reports_dir = Path(os.getenv("REPORTS_DIR", "forward_reports"))
        reports_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = reports_dir / "forward_summary.jsonl"

        # --- snapshot base del forward y acumulados que vienen de summary ---
        last_forward = dict(summary.get("forward", {}))
        totals = dict(summary.get("totals", {}))

        # --- tasks del forward + conteo por tipo en ESTE forward ---
        tasks = tasks or []
        fwd_counts = Counter((t.get("web_project", ""), t.get("use_case", "")) for t in tasks)
        last_forward["tasks"] = tasks
        last_forward["task_counts_by_type"] = [{"web": w, "use_case": uc, "tasks": c} for (w, uc), c in sorted(fwd_counts.items())]

        # --- conteo ACUMULADO por tipo (leyendo JSONL anterior) ---
        total_counts = Counter()
        if jsonl_path.exists():
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                # soporta formatos previos (tasks a nivel raíz o en last_forward)
                prev_tasks = rec.get("tasks", []) or rec.get("last_forward", {}).get("tasks", [])
                for t in prev_tasks:
                    total_counts[(t.get("web_project", ""), t.get("use_case", ""))] += 1

        # sumar también las tasks de este forward
        for (w, uc), c in fwd_counts.items():
            total_counts[(w, uc)] += c

        totals["task_counts_by_type"] = [{"web": w, "use_case": uc, "tasks": c} for (w, uc), c in sorted(total_counts.items())]

        # --- construir registro SOLO con last_forward y totals ---
        record = {
            "last_forward": last_forward,
            "totals": totals,
        }

        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        bt.logging.info("forward_summary.jsonl actualizado (last_forward + totals + tasks en last_forward).")
    except Exception as e:
        bt.logging.warning(f"No pude guardar forward_summary.jsonl: {e}")
