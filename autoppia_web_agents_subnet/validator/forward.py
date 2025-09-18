# autoppia_web_agents_subnet/validator/forward.py
from __future__ import annotations

import asyncio
import math
import random
import time
import json
import os
from pathlib import Path

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet import __version__
from autoppia_iwa.src.demo_webs.config import demo_web_projects
from autoppia_iwa.src.data_generation.domain.classes import Task

from autoppia_web_agents_subnet.validator.config import (
    FORWARD_SLEEP_SECONDS,
    NUMBER_OF_PROMPTS_PER_FORWARD,
    PROMPTS_PER_USECASE,
    SET_OPERATOR_ENDPOINT_FORWARDS_INTERVAL,
    SUCCESS_THRESHOLD,
)
from autoppia_web_agents_subnet.validator.stats import (
    init_validator_performance_stats,
    finalize_forward_stats,
)
from autoppia_web_agents_subnet.validator.visualization import print_forward_tables
from autoppia_web_agents_subnet.validator.forward_utils import (
    interleave_tasks,
    split_tasks_evenly,
    generate_tasks_limited_use_cases,
    evaluate_task_all_miners,  # devuelve (rewards_vec, avg_miner_time)
    broadcast_and_save_operator_endpoints,
    save_forward_report,
)


# ───────────────────────────────────────────────
# Forward principal
# ───────────────────────────────────────────────
async def forward(self) -> None:
    """
    Forward orchestration (all miners, average rewards):
      1) Generate N tasks across projects.
      2) For each task: evaluate ALL miners, accumulate rewards.
      3) After all tasks: update scores with average rewards per miner.
    """
    try:
        init_validator_performance_stats(self)
        self.forward_count += 1
        bt.logging.info(f"[forward #{self.forward_count}] start (version {__version__})")
        t_forward_start = time.time()

        num_projects = len(demo_web_projects)

        # 1) Generate tasks per project
        task_distribution = split_tasks_evenly(NUMBER_OF_PROMPTS_PER_FORWARD, num_projects)
        use_cases_per_project = max(1, math.ceil(NUMBER_OF_PROMPTS_PER_FORWARD / num_projects))
        bt.logging.info(f"Generating {NUMBER_OF_PROMPTS_PER_FORWARD} tasks across {num_projects} projects: " f"{task_distribution}, {use_cases_per_project} use-cases/project.")

        all_tasks: list[list[Task]] = []
        projects_with_tasks = []
        for project, num_tasks in zip(demo_web_projects, task_distribution):
            if num_tasks <= 0:
                continue
            project_tasks = await generate_tasks_limited_use_cases(
                project,
                total_tasks=num_tasks,
                prompts_per_use_case=PROMPTS_PER_USECASE,
                num_use_cases=use_cases_per_project,
            )
            if project_tasks:
                random.shuffle(project_tasks)
                all_tasks.append(project_tasks)
                projects_with_tasks.append(project)

        if not all_tasks:
            bt.logging.warning("No tasks generated – skipping forward.")
            return

        # 2) Acumular REWARDS
        n = self.metagraph.n
        accumulated_rewards = np.zeros(n, dtype=np.float32)
        tasks_evaluated_per_miner = np.zeros(n, dtype=np.int32)

        tasks_sent = 0
        tasks_success = 0
        sum_avg_response_times = 0.0
        miner_successes_total = 0
        miner_attempts_total = 0

        for task in interleave_tasks(*all_tasks):
            if tasks_sent >= NUMBER_OF_PROMPTS_PER_FORWARD:
                break

            project = None
            for p, project_tasks in zip(projects_with_tasks, all_tasks):
                if any(t is task for t in project_tasks):
                    project = p
                    break
            if project is None:
                bt.logging.warning(f"No project found for task {getattr(task, 'id', 'unknown')}")
                continue

            rewards_vec, avg_time = await evaluate_task_all_miners(self, project, task)

            accumulated_rewards += rewards_vec
            tasks_evaluated_per_miner += (rewards_vec >= 0).astype(np.int32)

            successes_mask = (rewards_vec > SUCCESS_THRESHOLD).astype(np.int32)
            miner_successes_total += int(np.sum(successes_mask))
            miner_attempts_total += rewards_vec.shape[0]

            tasks_sent += 1
            sum_avg_response_times += float(avg_time)
            if np.any(rewards_vec > SUCCESS_THRESHOLD):
                tasks_success += 1

        # 3) Actualizar scores con rewards promedio
        if tasks_sent > 0:
            tasks_evaluated_per_miner = np.maximum(tasks_evaluated_per_miner, 1)
            average_rewards = accumulated_rewards / tasks_evaluated_per_miner.astype(np.float32)

            bt.logging.info(f"Average rewards - Min: {average_rewards.min():.4f}, " f"Max: {average_rewards.max():.4f}, Mean: {average_rewards.mean():.4f}")

            uids_update = list(range(n))
            async with self.lock:
                self.update_scores(average_rewards, uids_update)

            bt.logging.info(f"[update] updated_uids={len(uids_update)} with average rewards")
        else:
            bt.logging.warning("[update] no tasks processed; scores unchanged.")

        # 4) Optional maintenance
        if self.forward_count % SET_OPERATOR_ENDPOINT_FORWARDS_INTERVAL == 0:
            await broadcast_and_save_operator_endpoints(self)

        # 5) Wrap-up
        forward_time = time.time() - t_forward_start
        summary = finalize_forward_stats(
            self,
            tasks_sent=tasks_sent,
            sum_avg_response_times=sum_avg_response_times,
            forward_time=forward_time,
            miner_successes=miner_successes_total,
            miner_attempts=miner_attempts_total,
            forward_id=self.forward_count,
        )

        avg_response_time = (sum_avg_response_times / tasks_sent) if tasks_sent else 0.0
        save_forward_report(
            self.forward_count,
            tasks_sent,
            miner_successes_total,
            miner_attempts_total,
            forward_time,
            avg_response_time,
            summary,
        )

        print_forward_tables(self.validator_performance_stats)
        bt.logging.success("Forward cycle completed!")

        if FORWARD_SLEEP_SECONDS > 0:
            bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s…")
            await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    except Exception as err:
        bt.logging.error(f"Error in forward: {err}")
