from __future__ import annotations

import asyncio
import math
import random
import time

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet import __version__
from autoppia_iwa.src.demo_webs.config import demo_web_projects

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
    process_tasks,
    broadcast_and_save_operator_endpoints,
)


async def forward(self) -> None:
    """
    Forward orchestration:
      1) Generate N tasks split across projects.
      2) Process tasks in an interleaved order.
      3) Update scores ONCE using the per-UID mean reward within this forward.
    """
    try:
        init_validator_performance_stats(self)
        self.forward_count += 1
        bt.logging.info(
            f"[forward #{self.forward_count}] start (version {__version__})"
        )
        t_forward_start = time.time()

        num_projects = len(demo_web_projects)
        if num_projects < 1:
            raise RuntimeError("At least one demo web project is required.")

        # 1) Task generation per project
        task_distribution = split_tasks_evenly(
            NUMBER_OF_PROMPTS_PER_FORWARD, num_projects
        )
        use_cases_per_project = max(
            1, math.ceil(NUMBER_OF_PROMPTS_PER_FORWARD / num_projects)
        )

        all_tasks: list[list] = []
        for project, num_tasks in zip(demo_web_projects, task_distribution):
            project_tasks = await generate_tasks_limited_use_cases(
                project,
                total_tasks=num_tasks,
                prompts_per_use_case=PROMPTS_PER_USECASE,
                num_use_cases=use_cases_per_project,
            )
            random.shuffle(project_tasks)
            all_tasks.append(project_tasks)

        total_tasks_generated = sum(len(t) for t in all_tasks)
        if total_tasks_generated == 0:
            bt.logging.warning("No tasks generated – skipping forward.")
            return

        # 2) Per-UID accumulators (we'll update scores once at the end)
        metagraph_n = self.metagraph.n
        batch_sum = np.zeros(metagraph_n, dtype=np.float32)
        batch_count = np.zeros(metagraph_n, dtype=np.int32)

        processed = 0
        for task in interleave_tasks(*all_tasks):
            if processed >= NUMBER_OF_PROMPTS_PER_FORWARD:
                break

            # Find the project that owns this task
            for project, project_tasks in zip(demo_web_projects, all_tasks):
                if task in project_tasks:
                    sum_inc, count_inc = await process_tasks(self, project, [task])

                    # accumulate first so "times" reflect the new count
                    batch_sum += sum_inc
                    batch_count += count_inc

                    # per-task log line per UID
                    task_idx = processed + 1
                    for uid in range(metagraph_n):
                        reward_val = float(
                            sum_inc[uid]
                        )  # reward on THIS task (0 if not sampled)
                        times_now = int(
                            batch_count[uid]
                        )  # total times seen in this forward
                        bt.logging.info(
                            f"[task {task_idx}/{NUMBER_OF_PROMPTS_PER_FORWARD}] "
                            f"UID {uid}: reward={reward_val:.3f} | times={times_now}"
                        )
                    break

            processed += 1

        # 3) Single score update at the end (mean per UID over this forward)
        mask = batch_count > 0
        if np.any(mask):
            avg_rewards = np.zeros_like(batch_sum, dtype=np.float32)
            avg_rewards[mask] = batch_sum[mask] / batch_count[mask]

            # pre-update logs: one line per UID with forward mean (or NA)
            for uid in range(metagraph_n):
                if batch_count[uid] > 0:
                    bt.logging.info(
                        f"[update] UID {uid}: forward_mean={float(avg_rewards[uid]):.3f}"
                    )
                else:
                    bt.logging.info(f"[update] UID {uid}: forward_mean=NA")

            uids_update = np.where(mask)[0].tolist()
            async with self.lock:
                self.update_scores(avg_rewards[mask], uids_update)
            bt.logging.info(f"[update] updated_uids={len(uids_update)}")
        else:
            bt.logging.warning("[update] no rewards this forward; scores unchanged.")

        # 4) Optional maintenance
        if self.forward_count % SET_OPERATOR_ENDPOINT_FORWARDS_INTERVAL == 0:
            await broadcast_and_save_operator_endpoints(self)

        # 5) Done + global forward metrics
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
