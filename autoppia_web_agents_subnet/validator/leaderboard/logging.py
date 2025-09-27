a
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
