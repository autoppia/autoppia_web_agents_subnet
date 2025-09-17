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

from autoppia_web_agents_subnet.validator.config import (
    FORWARD_SLEEP_SECONDS,
    NUMBER_OF_PROMPTS_PER_FORWARD,
    PROMPTS_PER_USECASE,
    SET_OPERATOR_ENDPOINT_FORWARDS_INTERVAL,
)
from autoppia_web_agents_subnet.validator.utils import (
    init_validator_performance_stats,
    print_validator_performance_stats,
)
from autoppia_web_agents_subnet.validator.forward_utils import (
    interleave_tasks,
    split_tasks_evenly,
    generate_tasks_limited_use_cases,
    evaluate_task_all_miners,  # evaluate each task against ALL miners
    broadcast_and_save_operator_endpoints,
)

SUCCESS_THRESHOLD = 0  # success if reward >= this value


async def forward(self) -> None:
    """
    Forward orchestration (all miners, success-ratio):
      1) Generate N tasks across projects.
      2) For each task: evaluate against ALL miners, accumulate successes.
      3) After all tasks: update scores ONCE with success_ratio = successes / tasks_processed.
    """
    try:
        init_validator_performance_stats(self)
        self.forward_count += 1
        bt.logging.info(
            f"[forward #{self.forward_count}] start (version {__version__})"
        )
        t_forward_start = time.time()

        num_projects = len(demo_web_projects)

        # 1) Generate tasks per project
        task_distribution = split_tasks_evenly(
            NUMBER_OF_PROMPTS_PER_FORWARD, num_projects
        )
        use_cases_per_project = max(
            1, math.ceil(NUMBER_OF_PROMPTS_PER_FORWARD / num_projects)
        )

        all_tasks: list[list[Task]] = []
        for project, num_tasks in zip(demo_web_projects, task_distribution):
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
        tasks_processed = 0

        for task in interleave_tasks(*all_tasks):
            if tasks_processed >= NUMBER_OF_PROMPTS_PER_FORWARD:
                break

            # Find project and evaluate this task for ALL miners
            for project, project_tasks in zip(demo_web_projects, all_tasks):
                if task in project_tasks:
                    rewards_vec = await evaluate_task_all_miners(self, project, task)
                    successes += (rewards_vec > SUCCESS_THRESHOLD).astype(np.int32)
                    tasks_processed += 1
                    break  # move to next task

        # 3) Single score update at the end: success ratio (e.g., 6/9, 8/9, ...)
        if tasks_processed > 0:
            success_ratio = successes.astype(np.float32) / float(tasks_processed)

            # Optional: per-UID compact logs
            for uid in range(n):
                bt.logging.info(
                    f"[update] UID {uid}: successes={int(successes[uid])}/{tasks_processed} "
                    f"=> ratio={float(success_ratio[uid]):.3f}"
                )

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
        self.validator_performance_stats["total_forwards_time"] += forward_time
        self.validator_performance_stats["total_forwards_count"] += 1

        print_validator_performance_stats(self)
        bt.logging.success("Forward cycle completed!")

        if FORWARD_SLEEP_SECONDS > 0:
            bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s…")
            await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    except Exception as err:
        bt.logging.error(f"Error in forward: {err}")
