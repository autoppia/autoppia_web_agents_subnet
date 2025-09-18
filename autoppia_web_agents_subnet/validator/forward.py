# autoppia_web_agents_subnet/validator/forward.py
from __future__ import annotations

import asyncio
import math
import random
import time

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet import __version__
from autoppia_iwa.src.demo_webs.config import demo_web_projects
from autoppia_iwa.src.data_generation.domain.classes import Task

from autoppia_web_agents_subnet.validator.config import FORWARD_SLEEP_SECONDS, NUMBER_OF_PROMPTS_PER_FORWARD, PROMPTS_PER_USECASE, SET_OPERATOR_ENDPOINT_FORWARDS_INTERVAL, SUCCESS_THRESHOLD
from autoppia_web_agents_subnet.validator.stats import (
    init_validator_performance_stats,
    finalize_forward_stats,
)
from autoppia_web_agents_subnet.validator.visualization import (
    print_forward_tables,
)
from autoppia_web_agents_subnet.validator.forward_utils import (
    interleave_tasks,
    split_tasks_evenly,
    generate_tasks_limited_use_cases,
    evaluate_task_all_miners,  # devuelve (rewards_vec, avg_miner_time)
    broadcast_and_save_operator_endpoints,
)


async def forward(self) -> None:
    """
    Forward orchestration (all miners, success-ratio):
      1) Generate N tasks across projects.
      2) For each task: evaluate ALL miners, accumulate successes and avg times.
      3) After all tasks: update scores ONCE with success_ratio = successes / tasks_processed,
         then log forward summary and cumulative totals.
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
        bt.logging.info(f"Generating {NUMBER_OF_PROMPTS_PER_FORWARD} tasks across {num_projects} projects: {task_distribution}, {use_cases_per_project} use-cases/project.")
        all_tasks: list[list[Task]] = []
        for project, num_tasks in zip(demo_web_projects, task_distribution):
            if num_tasks <= 0:
                continue
            project_tasks = await generate_tasks_limited_use_cases(
                project,
                total_tasks=num_tasks,
                prompts_per_use_case=PROMPTS_PER_USECASE,
                num_use_cases=use_cases_per_project,
            )
            random.shuffle(project_tasks)
            all_tasks.append(project_tasks)

        # 2) Success counters per UID (each task goes to ALL miners)
        n = self.metagraph.n
        successes = np.zeros(n, dtype=np.int32)

        # Per-forward accumulators
        tasks_sent = 0
        tasks_success = 0  # tasks with at least one miner reward > 0
        sum_avg_response_times = 0.0  # sum of per-task avg(miner) response time (seconds)

        miner_successes_total = 0
        miner_attempts_total = 0
        for task in interleave_tasks(*all_tasks):
            if tasks_sent >= NUMBER_OF_PROMPTS_PER_FORWARD:
                break

            # Find project and evaluate this task for ALL miners
            for project, project_tasks in zip(demo_web_projects, all_tasks):
                if task in project_tasks:
                    rewards_vec, avg_time = await evaluate_task_all_miners(self, project, task)
                    successes_mask = (rewards_vec > SUCCESS_THRESHOLD).astype(np.int32)
                    successes += successes_mask

                    miner_successes_total += int(np.sum(successes_mask))
                    miner_attempts_total += rewards_vec.shape[0]

                    tasks_sent += 1
                    sum_avg_response_times += float(avg_time)
                    if np.any(rewards_vec > SUCCESS_THRESHOLD):
                        tasks_success += 1
                    break

        # 3) Single score update at the end: success ratio (e.g., 6/9, 8/9, ...)
        if tasks_sent > 0:
            success_ratio = successes.astype(np.float32) / float(tasks_sent)

            # # Optional: per-UID compact logs
            # for uid in range(n):
            #     bt.logging.info(f"[update] UID {uid}: successes={int(successes[uid])}/{tasks_sent} => ratio={float(success_ratio[uid]):.3f}")
            uids_update = list(range(n))
            async with self.lock:
                self.update_scores(success_ratio, uids_update)
            bt.logging.info(f"[update] updated_uids={len(uids_update)}")
        else:
            bt.logging.warning("[update] no tasks processed; scores unchanged.")

        # 4) Optional maintenance
        if self.forward_count % SET_OPERATOR_ENDPOINT_FORWARDS_INTERVAL == 0:
            await broadcast_and_save_operator_endpoints(self)

        # 5) Wrap-up + global metrics
        forward_time = time.time() - t_forward_start

        # Persist + print summaries (forward + cumulative)
        summary = finalize_forward_stats(
            self,
            tasks_sent=tasks_sent,
            sum_avg_response_times=sum_avg_response_times,
            forward_time=forward_time,
            miner_successes=miner_successes_total,
            miner_attempts=miner_attempts_total,
            forward_id=self.forward_count,  # ← AÑADIDO
        )
        print_forward_tables(self.validator_performance_stats)

        bt.logging.success("Forward cycle completed!")

        if FORWARD_SLEEP_SECONDS > 0:
            bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s…")
            await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    except Exception as err:
        bt.logging.error(f"Error in forward: {err}")
