"""Evaluation-phase helper mixin used in tests."""

from __future__ import annotations
import asyncio
import inspect

from autoppia_web_agents_subnet.validator.evaluation.stateful_cua_eval import evaluate_with_stateful_cua
from autoppia_web_agents_subnet.validator.evaluation.rewards import calculate_reward_for_task
from autoppia_web_agents_subnet.validator import config as validator_config
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.opensource.utils_git import (
    normalize_and_validate_github_url,
    resolve_remote_ref_commit,
)


class ValidatorEvaluationMixin:
    """Mixin for evaluation phase."""

    async def _run_evaluation_phase(self) -> int:
        """
        Run the evaluation phase.

        Flow:
        1. Deploy all available agents
        2. For each task:
           - Evaluate all deployed agents
           - Send results to IWAP
        3. Cleanup agents
        """
        current_block = self.block
        self.round_manager.enter_phase(
            RoundPhase.EVALUATION,
            block=current_block,
            note="Starting evaluation phase",
        )
        ColoredLogger.info("Starting evaluation phase", ColoredLogger.MAGENTA)
        miners_reused = getattr(self, "miners_reused_this_round", None) or set()
        if miners_reused:
            reused_list = sorted(miners_reused)
            ColoredLogger.info(
                f"[reuse] {len(reused_list)} miner(s) reused this round (same commit), no re-eval: UIDs {reused_list}",
                ColoredLogger.GREEN,
            )

        # Get tasks for this round (all season tasks)
        season_tasks = None
        getter = getattr(self.round_manager, "get_round_tasks", None)
        if callable(getter):
            try:
                res = getter(current_block, self.season_manager)
                if inspect.isawaitable(res):
                    res = await res
                season_tasks = res
            except Exception:
                season_tasks = None
        if not isinstance(season_tasks, list):
            try:
                res = getattr(self.season_manager, "get_season_tasks")(current_block, self.round_manager)
                if inspect.isawaitable(res):
                    res = await res
                season_tasks = res
            except Exception:
                season_tasks = []

        total_tasks = len(season_tasks)

        # Round-based rate limiting metadata.
        round_number = 0
        season_number = None
        try:
            round_number = int(getattr(getattr(self, "round_manager", None), "round_number", 0) or 0)
        except Exception:
            round_number = 0
        try:
            season_number = int(getattr(getattr(self, "season_manager", None), "season_number", 0) or 0)
        except Exception:
            season_number = None

        def _finalize_agent(
            agent: object,
            *,
            score: float,
            zero_reason: str | None = None,
            register_commit: bool = True,
        ) -> None:
            """
            Mark an AgentInfo-like object as evaluated and persist it in agents_dict.
            When score is 0, zero_reason can be set for IWAP (e.g. over_cost_limit, task_timeout).
            """
            finalized_score: float = 0.0
            try:
                finalized_score = float(score)
                agent.score = finalized_score  # type: ignore[attr-defined]
            except Exception:
                try:
                    agent.score = 0.0  # type: ignore[attr-defined]
                except Exception:
                    pass
            if finalized_score <= 0.0 and zero_reason:
                try:
                    agent.zero_reason = zero_reason  # type: ignore[attr-defined]
                except Exception:
                    pass
            try:
                current_best = float(getattr(self, "_best_score_ever", 0.0) or 0.0)
            except Exception:
                current_best = 0.0
            if finalized_score > current_best:
                try:
                    self._best_score_ever = finalized_score
                except Exception:
                    pass
            try:
                agent.evaluated = True  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                agent.last_evaluated_round = round_number  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                if season_number:
                    agent.last_evaluated_season = season_number  # type: ignore[attr-defined]
            except Exception:
                pass
            # Clear any stale pending submission once we've processed the agent in this round.
            for attr in (
                "pending_github_url",
                "pending_agent_name",
                "pending_agent_image",
                "pending_normalized_repo",
                "pending_ref",
                "pending_received_round",
            ):
                try:
                    setattr(agent, attr, None)
                except Exception:
                    pass
            try:
                self.agents_dict[agent.uid] = agent  # type: ignore[attr-defined]
            except Exception:
                pass
            # Register (repo, commit) so we don't re-evaluate this miner on same commit in future rounds
            if register_commit:
                try:
                    run = getattr(self, "current_agent_runs", {}).get(getattr(agent, "uid", None))
                    normalized_repo = getattr(agent, "normalized_repo", None)
                    commit_sha = getattr(agent, "git_commit", None)
                    if run and normalized_repo and commit_sha:
                        acc = getattr(self, "agent_run_accumulators", {}).get(agent.uid, {})  # type: ignore[attr-defined]
                        tasks = int(acc.get("tasks", 0) or 0)
                        reward_sum = float(acc.get("reward", 0.0) or 0.0)
                        eval_sum = float(acc.get("eval_score", 0.0) or 0.0)
                        time_sum = float(acc.get("execution_time", 0.0) or 0.0)
                        avg_score = (eval_sum / tasks) if tasks else (getattr(run, "average_score", None) or 0.0)
                        avg_reward = (reward_sum / tasks) if tasks else (getattr(run, "average_reward", None) or 0.0)
                        avg_time = (time_sum / tasks) if tasks else (getattr(run, "average_execution_time", None) or 0.0)
                        round_rewards = getattr(getattr(self, "round_manager", None), "round_rewards", {}) or {}
                        miner_rewards = round_rewards.get(agent.uid, []) or []  # type: ignore[attr-defined]
                        success_tasks = len([r for r in miner_rewards if float(r) >= 0.5])
                        stats = {
                            "average_score": avg_score,
                            "average_reward": avg_reward,
                            "average_execution_time": avg_time,
                            "total_tasks": tasks or len(miner_rewards),
                            "success_tasks": success_tasks,
                            "failed_tasks": (tasks or len(miner_rewards)) - success_tasks,
                            "zero_reason": getattr(agent, "zero_reason", None),
                            "evaluated_season": int(getattr(getattr(self, "season_manager", None), "season_number", 0) or 0),
                            "evaluated_round": int(getattr(getattr(self, "round_manager", None), "round_number", 0) or 0),
                        }
                        self._register_evaluated_commit(  # type: ignore[attr-defined]
                            agent.uid,  # type: ignore[attr-defined]
                            str(normalized_repo),
                            str(commit_sha),
                            run.agent_run_id,
                            stats,
                        )
                except Exception:
                    pass

        agents_evaluated = 0
        while not self.agents_queue.empty():
            # Refresh block each loop iteration so settlement cutoff checks don't drift.
            current_block = self.block
            stop_fraction = float(
                getattr(
                    validator_config,
                    "STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION",
                    1.0,
                )
                or 1.0
            )
            stop_fraction = max(0.0, min(1.0, stop_fraction))
            fraction_elapsed = float(self.round_manager.fraction_elapsed(current_block))
            if fraction_elapsed >= stop_fraction:
                ColoredLogger.info(
                    f"Stopping evaluation at round fraction {fraction_elapsed:.4f} (limit={stop_fraction:.4f})",
                    ColoredLogger.YELLOW,
                )
                # Keep run accounting coherent for miners still pending in queue:
                # they participated in handshake/start_agent_run but were skipped
                # due round deadline. Persist deterministic 0-reward task stats
                # so IWAP/DB never stores 0/0 placeholders for these runs.
                task_timeout_sec = float(getattr(validator_config, "TASK_TIMEOUT_SECONDS", 180.0) or 180.0)
                pending_agents = []
                while not self.agents_queue.empty():
                    try:
                        pending_agents.append(self.agents_queue.get_nowait())
                    except Exception:
                        break
                if pending_agents:
                    round_rewards = getattr(getattr(self, "round_manager", None), "round_rewards", None)
                    round_eval_scores = getattr(getattr(self, "round_manager", None), "round_eval_scores", None)
                    round_times = getattr(getattr(self, "round_manager", None), "round_times", None)
                    for pending_agent in pending_agents:
                        try:
                            pending_uid = int(getattr(pending_agent, "uid"))
                        except Exception:
                            continue
                        try:
                            acc = getattr(self, "agent_run_accumulators", {}).setdefault(
                                pending_uid,
                                {"reward": 0.0, "eval_score": 0.0, "execution_time": 0.0, "tasks": 0},
                            )
                            if int(acc.get("tasks", 0) or 0) <= 0 and total_tasks > 0:
                                acc["tasks"] = int(total_tasks)
                                acc["reward"] = 0.0
                                acc["eval_score"] = 0.0
                                acc["execution_time"] = float(task_timeout_sec) * float(total_tasks)
                        except Exception:
                            pass

                        if isinstance(round_rewards, dict):
                            round_rewards[pending_uid] = [0.0] * int(total_tasks)
                        if isinstance(round_eval_scores, dict):
                            round_eval_scores[pending_uid] = [0.0] * int(total_tasks)
                        if isinstance(round_times, dict):
                            round_times[pending_uid] = [float(task_timeout_sec)] * int(total_tasks)

                        run = getattr(self, "current_agent_runs", {}).get(pending_uid)
                        if run is not None:
                            try:
                                run.total_tasks = int(total_tasks)
                                run.completed_tasks = 0
                                run.failed_tasks = int(total_tasks)
                                run.average_score = 0.0
                                run.average_reward = 0.0
                                run.average_execution_time = float(task_timeout_sec)
                                run.zero_reason = "round_window_exceeded"
                            except Exception:
                                pass

                        _finalize_agent(
                            pending_agent,
                            score=0.0,
                            zero_reason="round_window_exceeded",
                            register_commit=False,
                        )
                return agents_evaluated

            agent = self.agents_queue.get()

            agent_instance = None
            # Pre-validate GitHub URL to avoid expensive docker/git work for
            # obviously invalid miner submissions.
            raw_github_url = getattr(agent, "github_url", None)
            require_ref = True
            try:
                validated = normalize_and_validate_github_url(
                    raw_github_url,
                    miner_uid=getattr(agent, "uid", None),
                    require_ref=require_ref,
                )
                if isinstance(validated, tuple):
                    normalized_url, ref = validated
                else:
                    normalized_url, ref = validated, None
                if not normalized_url:
                    ColoredLogger.warning(
                        f"Skipping agent {getattr(agent, 'uid', '?')}: invalid github_url={getattr(agent, 'github_url', None)}",
                        ColoredLogger.YELLOW,
                    )
                    _finalize_agent(agent, score=0.0, zero_reason="invalid_github_url")
                    continue

                # Strict: ensure the submitted ref exists / repo is reachable via git
                # before spending resources cloning/building.
                raw_s = str(raw_github_url or "")
                is_commit_url = "/commit/" in raw_s
                if is_commit_url:
                    # We can't ls-remote a commit hash directly, but we can at least
                    # ensure the repo is reachable.
                    if resolve_remote_ref_commit(str(normalized_url), "HEAD") is None:
                        ColoredLogger.warning(
                            f"Skipping agent {getattr(agent, 'uid', '?')}: git ls-remote failed (repo unreachable)",
                            ColoredLogger.YELLOW,
                        )
                        _finalize_agent(agent, score=0.0, zero_reason="repo_unreachable")
                        continue
                else:
                    if require_ref and not ref:
                        ColoredLogger.warning(
                            f"Skipping agent {getattr(agent, 'uid', '?')}: missing required ref in github_url={raw_s}",
                            ColoredLogger.YELLOW,
                        )
                        _finalize_agent(agent, score=0.0, zero_reason="missing_ref")
                        continue
                    if ref and resolve_remote_ref_commit(str(normalized_url), str(ref)) is None:
                        ColoredLogger.warning(
                            f"Skipping agent {getattr(agent, 'uid', '?')}: git ls-remote failed for ref={ref}",
                            ColoredLogger.YELLOW,
                        )
                        _finalize_agent(agent, score=0.0, zero_reason="ref_not_found")
                        continue
            except Exception as exc:
                ColoredLogger.warning(
                    f"Skipping agent {getattr(agent, 'uid', '?')}: github_url pre-validation failed: {exc}",
                    ColoredLogger.YELLOW,
                )
                _finalize_agent(agent, score=0.0)
                continue
            try:
                agent_instance = self.sandbox_manager.deploy_agent(agent.uid, agent.github_url)
            except Exception as e:
                ColoredLogger.error(f"Error deploying agent {agent.uid}: {e}", ColoredLogger.RED)
                _finalize_agent(agent, score=0.0)
                continue

            if agent_instance is None:
                ColoredLogger.error(f"Agent not deployed correctly for uid {agent.uid}", ColoredLogger.RED)
                _finalize_agent(agent, score=0.0)
                continue

            # Persist the exact evaluated code identity for future "skip re-eval"
            # checks (resolved during clone, not from miner-provided metadata).
            try:
                if normalized_url:
                    agent.normalized_repo = str(normalized_url)
            except Exception:
                pass
            try:
                commit = getattr(agent_instance, "git_commit", None)
                if commit:
                    agent.git_commit = str(commit)
            except Exception:
                pass

            try:
                setter = getattr(self.sandbox_manager, "set_allowed_task_ids", None)
                if callable(setter):
                    task_ids: list[str] = []
                    for task_item in season_tasks:
                        tid = getattr(getattr(task_item, "task", None), "id", None)
                        if tid is not None:
                            task_ids.append(str(tid))
                    ok = setter(task_ids=task_ids)
                    if ok is False:
                        ColoredLogger.warning(
                            f"Gateway rejected allowed task ids for agent {agent.uid}; cost accounting may be incomplete",
                            ColoredLogger.YELLOW,
                        )
            except Exception as exc:
                ColoredLogger.warning(
                    f"Failed to set allowed task ids for agent {agent.uid}: {exc}",
                    ColoredLogger.YELLOW,
                )

            rewards: list[float] = []
            eval_details: list[tuple[float, float]] = []  # (score, exec_time_s) per evaluated task (for task_timeout detection)
            task_timeout_sec = float(getattr(validator_config, "TASK_TIMEOUT_SECONDS", 180.0) or 180.0)
            batch_size = int(getattr(validator_config, "CONCURRENT_EVALUATION_NUM", 1) or 1)
            max_steps = int(getattr(validator_config, "AGENT_MAX_STEPS", 30) or 30)
            cost_limit_exceed_count = int(
                getattr(
                    validator_config,
                    "MAX_OVER_COST_TASKS_BEFORE_FORCED_ZERO_SCORE",
                    0,
                )
                or 0
            )
            max_cost_per_task = float(getattr(validator_config, "MAX_TASK_DOLLAR_COST_USD", 0.0) or 0.0)
            cost_limit_hits = 0
            tasks_evaluated_for_agent = 0
            stop_for_cost_limit_streak = False

            try:
                for i in range(0, len(season_tasks), batch_size):
                    batch_tasks = season_tasks[i : i + batch_size]
                    eval_results = await asyncio.gather(
                        *[
                            evaluate_with_stateful_cua(
                                task=task_item.task,
                                uid=agent.uid,
                                base_url=agent_instance.base_url,
                                max_steps=max_steps,
                            )
                            for task_item in batch_tasks
                        ],
                        return_exceptions=True,
                    )

                    # Prepare batch data for IWAP submission
                    batch_eval_data = []  # Store (task_item, score, exec_time, cost, reward, eval_result)

                    for task_item, eval_result in zip(batch_tasks, eval_results):
                        tasks_evaluated_for_agent += 1
                        if isinstance(eval_result, Exception):
                            ColoredLogger.error(
                                f"Error evaluating agent {agent.uid} on task {task_item.task.id}: {eval_result}",
                                ColoredLogger.RED,
                            )
                            continue

                        score, exec_time, task_solution = eval_result
                        try:
                            exec_time_s = float(exec_time) if exec_time is not None else 0.0
                        except Exception:
                            exec_time_s = 0.0

                        usage_for_task = None
                        try:
                            getter = getattr(self.sandbox_manager, "get_usage_for_task", None)
                            if callable(getter):
                                usage_for_task = getter(task_id=task_item.task.id)
                        except Exception:
                            usage_for_task = None
                        if not isinstance(usage_for_task, dict):
                            usage_for_task = None

                        try:
                            cost = float((usage_for_task or {}).get("total_cost", 0.0))
                        except Exception:
                            cost = 0.0
                        try:
                            tokens = int((usage_for_task or {}).get("total_tokens", 0))
                        except Exception:
                            tokens = 0

                        # Build per-provider/model usage list for backend (evaluation_llm_usage)
                        llm_usage: list[dict] = []
                        try:
                            usage_details = (usage_for_task or {}).get("usage_details") or {}
                            tokens_map = usage_details.get("tokens") or {}
                            cost_map = usage_details.get("cost") or {}
                            for provider, models in tokens_map.items():
                                if not isinstance(models, dict):
                                    continue
                                for model, tk in models.items():
                                    try:
                                        tk_val = int(tk or 0)
                                    except Exception:
                                        tk_val = 0
                                    try:
                                        cost_val = float((cost_map.get(provider) or {}).get(model) or 0.0)
                                    except Exception:
                                        cost_val = 0.0
                                    llm_usage.append(
                                        {
                                            "provider": provider,
                                            "model": model,
                                            "tokens": tk_val,
                                            "cost": cost_val,
                                        }
                                    )
                        except Exception:
                            llm_usage = []

                        if usage_for_task and not llm_usage:
                            ColoredLogger.warning(
                                f"LLM usage details missing or unparseable for task {task_item.task.id}: keys={list((usage_for_task or {}).keys())}",
                                ColoredLogger.YELLOW,
                            )
                        elif llm_usage:
                            ColoredLogger.info(
                                f"LLM usage parsed for task {task_item.task.id}: {llm_usage}",
                                ColoredLogger.CYAN,
                            )

                        llm_calls = None
                        try:
                            calls = (usage_for_task or {}).get("calls")
                            if isinstance(calls, list):
                                llm_calls = calls
                        except Exception:
                            llm_calls = None

                        try:
                            score_f = float(score)
                        except Exception:
                            score_f = 0.0

                        ColoredLogger.info(
                            f"  Agent {agent.uid}: score={score_f:.3f}, time={exec_time_s:.2f}s, cost=${cost:.4f}, tokens={tokens}",
                            ColoredLogger.CYAN,
                        )
                        # Avoid logging huge payloads (DOM snapshots, base64 blobs) that can appear in
                        # TaskSolution.recording/execution_history. Keep logs readable and prevent PM2
                        # log files from ballooning.
                        try:
                            from autoppia_iwa.src.web_agents.classes import TaskSolution as _TaskSolution  # type: ignore
                        except Exception:  # pragma: no cover
                            _TaskSolution = None

                        def _summarize_task_solution(ts) -> str:
                            try:
                                if _TaskSolution is not None and isinstance(ts, _TaskSolution):
                                    actions = getattr(ts, "actions", []) or []
                                    task_id = getattr(ts, "task_id", None)
                                    recording = getattr(ts, "recording", None)
                                    rec_keys = []
                                    exec_hist_len = 0
                                    gif_present = False
                                    if isinstance(recording, dict):
                                        rec_keys = sorted(list(recording.keys()))
                                        hist = recording.get("execution_history")
                                        if isinstance(hist, list):
                                            exec_hist_len = len(hist)
                                        gif_present = bool(recording.get("gif_recording"))
                                    elif isinstance(recording, list):
                                        exec_hist_len = len(recording)
                                    action_types = []
                                    for a in actions[:3]:
                                        t = getattr(a, "type", None) or (a.get("type") if isinstance(a, dict) else None)
                                        if t:
                                            action_types.append(str(t))
                                    return (
                                        f"TaskSolution(task_id={task_id!r}, actions={len(actions)}, "
                                        f"action_types={action_types}, recording_keys={rec_keys}, "
                                        f"execution_history={exec_hist_len}, gif_present={gif_present})"
                                    )
                                if isinstance(ts, dict):
                                    keys = sorted(list(ts.keys()))
                                    hist = ts.get("execution_history")
                                    hist_len = len(hist) if isinstance(hist, list) else 0
                                    return f"TaskSolution(dict keys={keys}, execution_history={hist_len})"
                            except Exception:
                                pass
                            return f"TaskSolution(type={type(ts).__name__})"

                        ColoredLogger.debug(f"    Task solution: {_summarize_task_solution(task_solution)}", ColoredLogger.BLUE)

                        # Log actions returned by the miner for easy grep/debug.
                        try:
                            action_list = []
                            if isinstance(task_solution, dict):
                                action_list = task_solution.get("actions") or []
                            else:
                                action_list = getattr(task_solution, "actions", []) or []
                            action_types = []
                            for a in action_list:
                                t = getattr(a, "type", None) or (a.get("type") if isinstance(a, dict) else None)
                                if t:
                                    action_types.append(str(t))
                            ColoredLogger.info(
                                f"[MINER_ACTIONS] task_id={task_item.task.id} uid={agent.uid} actions={action_types}",
                                ColoredLogger.CYAN,
                            )
                        except Exception:
                            pass

                        # Log the actions actually executed by the evaluator (execution_history).
                        # This is the ground truth used for backend event checks.
                        try:
                            recording = None
                            if isinstance(task_solution, dict):
                                recording = task_solution.get("recording")
                            else:
                                recording = getattr(task_solution, "recording", None)

                            exec_hist = None
                            if isinstance(recording, dict):
                                exec_hist = recording.get("execution_history")
                            elif isinstance(recording, list):
                                exec_hist = recording

                            exec_types = []
                            last_url = None
                            if isinstance(exec_hist, list):
                                for h in exec_hist:
                                    a = getattr(h, "action", None) if not isinstance(h, dict) else h.get("action")
                                    if isinstance(a, dict):
                                        t = a.get("type")
                                    else:
                                        t = getattr(a, "type", None)
                                    if t:
                                        exec_types.append(str(t))
                                    snap = getattr(h, "browser_snapshot", None) if not isinstance(h, dict) else h.get("browser_snapshot")
                                    if isinstance(snap, dict):
                                        last_url = snap.get("current_url") or snap.get("url") or last_url
                                    else:
                                        last_url = getattr(snap, "current_url", None) or last_url

                            ColoredLogger.info(
                                f"[EXEC_ACTIONS] task_id={task_item.task.id} uid={agent.uid} actions={exec_types} last_url={last_url}",
                                ColoredLogger.CYAN,
                            )

                            # Detect and surface cases where the miner returned N actions but the evaluator executed M.
                            # This helps confirm/deny "missing last action" hypotheses quickly.
                            try:
                                miner_n = len(action_list) if isinstance(action_list, list) else 0
                                exec_n = len(exec_hist) if isinstance(exec_hist, list) else 0
                                if miner_n != exec_n:
                                    ColoredLogger.warning(
                                        f"[MISMATCH_MINER_EXEC] task_id={task_item.task.id} uid={agent.uid} miner_actions={miner_n} exec_actions={exec_n}",
                                        ColoredLogger.YELLOW,
                                    )
                            except Exception:
                                pass
                        except Exception:
                            pass

                        reward = calculate_reward_for_task(
                            eval_score=score_f,
                            execution_time=exec_time_s,
                            token_cost=cost,
                        )
                        rewards.append(reward)
                        eval_details.append((score_f, exec_time_s))

                        if cost_limit_exceed_count > 0 and max_cost_per_task > 0.0 and cost >= max_cost_per_task - 1e-12:
                            cost_limit_hits += 1
                            ColoredLogger.warning(
                                f"Agent {agent.uid} exceeded task cost limit on task {tasks_evaluated_for_agent}/{total_tasks}: "
                                f"${cost:.4f} (limit={max_cost_per_task:.4f}, count={cost_limit_hits}/{cost_limit_exceed_count})",
                                ColoredLogger.YELLOW,
                            )
                            if cost_limit_hits >= cost_limit_exceed_count:
                                ColoredLogger.warning(
                                    f"Agent {agent.uid} hit max over-cost task limit ({cost_limit_exceed_count}); stopping remaining tasks and forcing score=0",
                                    ColoredLogger.YELLOW,
                                )
                                stop_for_cost_limit_streak = True

                        # zero_reason para IWAP cuando hay timeout (backend usa zero_reason, no metadata.timeout)
                        zero_reason_task = "task_timeout" if (score_f <= 0.0 and exec_time_s >= task_timeout_sec) else None
                        # Store evaluation data for batch submission
                        batch_eval_data.append(
                            {
                                "task_item": task_item,
                                "score": score_f,
                                "exec_time": exec_time_s,
                                "cost": cost,
                                "tokens": tokens,
                                "reward": reward,
                                "task_solution": task_solution,
                                "llm_usage": llm_usage,
                                "llm_calls": llm_calls,
                                "zero_reason": zero_reason_task,
                            }
                        )

                    # Submit batch evaluations to IWAP
                    if batch_eval_data:
                        try:
                            submitted = await self._submit_batch_evaluations_to_iwap(
                                agent_uid=agent.uid,
                                batch_eval_data=batch_eval_data,
                            )
                            if submitted:
                                ColoredLogger.info(
                                    f"✅ Submitted {len(batch_eval_data)} evaluations to IWAP for agent {agent.uid}",
                                    ColoredLogger.GREEN,
                                )
                            else:
                                ColoredLogger.warning(
                                    f"IWAP submission skipped for agent {agent.uid}; evaluations kept local only",
                                    ColoredLogger.YELLOW,
                                )
                        except Exception as e:
                            ColoredLogger.error(
                                f"Failed to submit batch evaluations to IWAP for agent {agent.uid}: {e}",
                                ColoredLogger.RED,
                            )

                    if stop_for_cost_limit_streak:
                        break
            finally:
                # Always cleanup the agent container after evaluation.
                try:
                    cleanup = getattr(self.sandbox_manager, "cleanup_agent", None)
                    if callable(cleanup):
                        cleanup(agent.uid)
                except Exception:
                    pass

            # Update agent score/evaluated state and increment the counter.
            if stop_for_cost_limit_streak:
                ColoredLogger.warning(
                    f"Agent {agent.uid} stopped after {tasks_evaluated_for_agent}/{total_tasks} evaluated tasks "
                    f"due to {cost_limit_hits} over-cost tasks (limit={cost_limit_exceed_count}); final score forced to 0",
                    ColoredLogger.YELLOW,
                )
                _finalize_agent(agent, score=0.0, zero_reason="over_cost_limit")
            else:
                avg_reward = (sum(rewards) / float(total_tasks)) if total_tasks > 0 else 0.0
                if avg_reward <= 0.0:
                    # All evaluated tasks failed: distinguish timeout vs other failure
                    if eval_details and all(score <= 0.0 and exec_time >= task_timeout_sec for score, exec_time in eval_details):
                        zero_reason = "task_timeout"
                    else:
                        zero_reason = "all_tasks_failed"
                else:
                    zero_reason = None
                _finalize_agent(agent, score=float(avg_reward), zero_reason=zero_reason)
            agents_evaluated += 1

        ColoredLogger.info("Evaluation phase completed", ColoredLogger.MAGENTA)
        return agents_evaluated

    async def _submit_batch_evaluations_to_iwap(
        self,
        *,
        agent_uid: int,
        batch_eval_data: list,
    ) -> bool:
        """
        Submit a batch of evaluations to IWAP for a single agent.

        This method prepares evaluation payloads for all tasks in the batch
        and sends them in a single HTTP request to IWAP.

        Args:
            agent_uid: The UID of the agent being evaluated
            batch_eval_data: List of dicts containing evaluation data:
                - task_item: Task with project
                - score: Evaluation score
                - exec_time: Execution time
                - cost: Token cost
                - reward: Calculated reward
                - task_solution: TaskSolution from evaluate_with_stateful_cua
        """
        if not hasattr(self, "current_round_id") or not self.current_round_id:
            ColoredLogger.warning("No current round ID, skipping IWAP submission", ColoredLogger.YELLOW)
            return False

        if getattr(self, "_iwap_offline_mode", False):
            ColoredLogger.warning("IWAP offline mode enabled, skipping IWAP submission", ColoredLogger.YELLOW)
            return False
        if getattr(self, "_iwap_shadow_mode", False):
            ColoredLogger.warning("IWAP shadow mode enabled, continuing IWAP submission with idempotent writes", ColoredLogger.YELLOW)

        if not hasattr(self, "current_agent_runs") or agent_uid not in self.current_agent_runs:
            ColoredLogger.warning(f"No agent run found for agent {agent_uid}, skipping IWAP submission", ColoredLogger.YELLOW)
            return False

        agent_run = self.current_agent_runs[agent_uid]

        # Prepare all evaluation payloads
        from autoppia_web_agents_subnet.platform.utils.task_flow import prepare_evaluation_payload
        from autoppia_web_agents_subnet.platform.utils.iwa_core import extract_gif_bytes

        evaluations_batch = []
        pending_gif_uploads: list[tuple[str, object]] = []
        for eval_data in batch_eval_data:
            task_item = eval_data["task_item"]

            # Get task payload from current round tasks
            base_task_id = getattr(task_item.task, "id", None)
            if base_task_id is None:
                continue

            # Build the full task_id that matches what was stored in IWAP
            full_task_id = f"{self.current_round_id}_{base_task_id}"
            task_payload = self.current_round_tasks.get(full_task_id)
            if task_payload is None:
                task_payload = self.current_round_tasks.get(base_task_id)
            if task_payload is None:
                ColoredLogger.warning(f"Task {base_task_id} not found in current round tasks", ColoredLogger.YELLOW)
                continue

            # task_solution comes from evaluate_with_stateful_cua (TaskSolution); support dict for backwards compat
            task_solution = eval_data["task_solution"]

            # Extract solution and actions
            solution = None
            actions = []
            test_results_data = []
            evaluation_meta_dict = {}

            from autoppia_iwa.src.web_agents.classes import TaskSolution

            if isinstance(task_solution, TaskSolution):
                solution = task_solution
                actions = getattr(solution, "actions", []) or []
                # If the solution carries execution history, attach it for backend persistence.
                recording = getattr(solution, "recording", None)
                execution_history_payload = None
                gif_payload = None
                if isinstance(recording, dict):
                    execution_history_payload = recording.get("execution_history")
                    gif_payload = recording.get("gif_recording")
                elif isinstance(recording, list):
                    execution_history_payload = recording

                if isinstance(execution_history_payload, list) and execution_history_payload:
                    serialized_history: list[dict] = []
                    for item in execution_history_payload:
                        if hasattr(item, "model_dump"):
                            try:
                                serialized_history.append(item.model_dump(mode="json", exclude_none=True))
                                continue
                            except Exception:
                                pass
                        if isinstance(item, dict):
                            serialized_history.append(item)
                    if serialized_history:
                        evaluation_meta_dict["execution_history"] = serialized_history

                if gif_payload:
                    evaluation_meta_dict["gif_recording"] = gif_payload
            elif isinstance(task_solution, dict):
                # Legacy: dict form (e.g. execution_history, test_results)
                evaluation_meta_dict = task_solution
                # Extract actions from execution_history if present
                if "execution_history" in task_solution:
                    execution_history = task_solution["execution_history"]
                    if isinstance(execution_history, list):
                        for step in execution_history:
                            if isinstance(step, dict) and "action" in step:
                                actions.append(step["action"])
                # Extract test_results
                test_results_data = task_solution.get("test_results", [])
                # Create solution object with extracted actions
                solution = TaskSolution(task_id=base_task_id, actions=actions, web_agent_id=str(agent_uid))
            else:
                # Fallback: create empty solution
                solution = TaskSolution(task_id=base_task_id, actions=[], web_agent_id=str(agent_uid))

            if not isinstance(evaluation_meta_dict, dict):
                evaluation_meta_dict = {}
            else:
                evaluation_meta_dict = dict(evaluation_meta_dict)
            if isinstance(eval_data.get("llm_usage"), list):
                evaluation_meta_dict["llm_usage"] = eval_data.get("llm_usage")
            if isinstance(eval_data.get("llm_calls"), list):
                evaluation_meta_dict["llm_calls"] = eval_data.get("llm_calls")

            evaluation_payload = prepare_evaluation_payload(
                ctx=self,
                task_payload=task_payload,
                agent_run=agent_run,
                miner_uid=agent_uid,
                solution=solution,
                eval_score=eval_data["score"],
                evaluation_meta=evaluation_meta_dict,
                test_results_data=test_results_data,
                exec_time=eval_data["exec_time"],
                reward=eval_data["reward"],
                zero_reason=eval_data.get("zero_reason"),
            )

            evaluations_batch.append(evaluation_payload)

            def _action_to_dict(a):
                if a is None:
                    return None
                if isinstance(a, dict):
                    return a
                d = {}
                for k in ("type", "url", "text", "go_back", "go_forward", "x", "y"):
                    v = getattr(a, k, None)
                    if v is not None:
                        d[k] = v
                sel = getattr(a, "selector", None)
                if sel is not None:
                    d["selector"] = sel if isinstance(sel, dict) else getattr(sel, "__dict__", str(sel))
                return d or {"type": getattr(a, "type", type(a).__name__)}

            # Extract the executed actions from the evaluator recording (ground truth).
            exec_actions = []
            try:
                ts_obj = eval_data.get("task_solution")
                recording = ts_obj.get("recording") if isinstance(ts_obj, dict) else getattr(ts_obj, "recording", None)
                exec_hist = None
                if isinstance(recording, dict):
                    exec_hist = recording.get("execution_history")
                elif isinstance(recording, list):
                    exec_hist = recording
                if isinstance(exec_hist, list):
                    for h in exec_hist:
                        a = getattr(h, "action", None) if not isinstance(h, dict) else h.get("action")
                        exec_actions.append(_action_to_dict(a))
            except Exception:
                exec_actions = []

            # Emit a compact log of what will be persisted to IWAP.
            actions = []
            try:
                ts = evaluation_payload.get("task_solution") if isinstance(evaluation_payload, dict) else None
                if isinstance(ts, dict):
                    actions = ts.get("actions") or []
                action_types = []
                for a in actions:
                    if isinstance(a, dict) and a.get("type"):
                        action_types.append(str(a.get("type")))
                ColoredLogger.info(
                    f"[IWAP_ACTIONS] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} actions={action_types}",
                    ColoredLogger.CYAN,
                )
            except Exception:
                pass

            # Optional: upload task execution log for S3-backed storage (batch path)
            if getattr(self, "iwap_client", None):
                task_log_miner_uid = agent_uid
                try:
                    task_log_miner_uid = int(task_log_miner_uid)
                    from autoppia_web_agents_subnet.platform.utils.task_flow import _build_task_log_payload

                    task_log_payload = _build_task_log_payload(
                        task_payload=task_payload,
                        agent_run=agent_run,
                        miner_uid=task_log_miner_uid,
                        eval_score=eval_data["score"],
                        reward=eval_data["reward"],
                        exec_time=eval_data["exec_time"],
                        evaluation_meta=evaluation_meta_dict,
                        validator_round_id=self.current_round_id,
                        validator_uid=int(self.uid),
                    )
                    try:
                        pl = task_log_payload.get("payload") if isinstance(task_log_payload, dict) else None
                        steps = pl.get("steps") if isinstance(pl, dict) else None
                        s3_actions = []
                        if isinstance(steps, list) and steps:
                            for step in steps:
                                if not isinstance(step, dict):
                                    continue
                                ao = step.get("agent_output")
                                if not isinstance(ao, dict):
                                    continue
                                act = ao.get("action")
                                if isinstance(act, dict):
                                    s3_actions.append(act)
                        s3_types = [a.get("type") for a in s3_actions if isinstance(a, dict) and a.get("type")]
                        ColoredLogger.info(
                            f"[S3_ACTIONS] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} actions={s3_types}",
                            ColoredLogger.CYAN,
                        )

                        # Compare executed vs persisted-to-IWAP vs persisted-to-S3 action counts.
                        try:
                            iwap_n = len(actions) if isinstance(actions, list) else 0
                            exec_n = len(exec_actions) if isinstance(exec_actions, list) else 0
                            s3_n = len(s3_actions) if isinstance(s3_actions, list) else 0
                            if (exec_n and exec_n != iwap_n) or (exec_n and exec_n != s3_n) or (iwap_n and iwap_n != s3_n):
                                ColoredLogger.warning(
                                    f"[MISMATCH_ACTIONS] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} exec={exec_n} iwap={iwap_n} s3={s3_n}",
                                    ColoredLogger.YELLOW,
                                )
                        except Exception:
                            pass
                    except Exception:
                        pass
                    task_log_url = await self.iwap_client.upload_task_log(task_log_payload)
                    if task_log_url:
                        task_logs_payload = getattr(self, "_s3_task_log_urls", None)
                        if not isinstance(task_logs_payload, list):
                            task_logs_payload = []
                        task_logs_payload.append(
                            {
                                "task_id": full_task_id,
                                "agent_run_id": agent_run.agent_run_id,
                                "miner_uid": task_log_miner_uid,
                                "url": task_log_url,
                                "payload": {
                                    "season": task_log_payload.get("season"),
                                    "round_in_season": task_log_payload.get("round_in_season"),
                                },
                            }
                        )
                        self._s3_task_log_urls = task_logs_payload
                except Exception as log_exc:  # noqa: BLE001
                    ColoredLogger.warning(
                        f"Task log upload failed for task_id={getattr(task_payload, 'task_id', None)} miner_uid={task_log_miner_uid}: {log_exc}",
                        ColoredLogger.YELLOW,
                    )
                # Upload evaluation metadata to Hippius S3 (independent of IWAP success)
                try:
                    from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_metadata_async

                    await upload_evaluation_metadata_async(
                        round_id=self.current_round_id,
                        validator_uid=int(self.uid),
                        miner_uid=agent_uid,
                        metadata=task_log_payload,
                        task_id=task_log_payload.get("task_id") if isinstance(task_log_payload, dict) else None,
                    )
                except Exception as s3_exc:  # noqa: BLE001
                    ColoredLogger.debug(f"Hippius S3 metadata upload failed (non-critical): {s3_exc}")
            gif_payload = evaluation_meta_dict.get("gif_recording")
            evaluation_result = evaluation_payload.get("evaluation_result", {})
            evaluation_id = evaluation_result.get("evaluation_id") if isinstance(evaluation_result, dict) else None
            if evaluation_id and gif_payload:
                pending_gif_uploads.append((str(evaluation_id), gif_payload, full_task_id))

        if not evaluations_batch:
            ColoredLogger.warning("No evaluations to submit in batch", ColoredLogger.YELLOW)
            return False

        # Submit batch to IWAP
        if hasattr(self, "iwap_client") and self.iwap_client:
            try:
                result = await self.iwap_client.add_evaluations_batch(
                    validator_round_id=self.current_round_id,
                    agent_run_id=agent_run.agent_run_id,
                    evaluations=evaluations_batch,
                )
                created = int(result.get("evaluations_created") or 0) if isinstance(result, dict) else 0
                total = int(result.get("total_requested") or len(evaluations_batch)) if isinstance(result, dict) else len(evaluations_batch)
                if created < total:
                    ColoredLogger.error(
                        f"Batch submission incomplete: created={created} total={total} message={result.get('message')}",
                        ColoredLogger.RED,
                    )
                    if isinstance(result, dict) and result.get("errors"):
                        ColoredLogger.error(f"Batch errors: {result.get('errors')}", ColoredLogger.RED)
                else:
                    ColoredLogger.info(f"Batch submission result: {result.get('message', 'Success')}", ColoredLogger.GREEN)

                # Batch endpoint stores evaluations but does not upload GIF binaries.
                # Upload each GIF separately using the deterministic evaluation_id.
                if pending_gif_uploads:
                    uploaded = 0
                    skipped = 0
                    for evaluation_id, gif_payload, _task_id in pending_gif_uploads:
                        gif_bytes = extract_gif_bytes(gif_payload)
                        if not gif_bytes:
                            skipped += 1
                            ColoredLogger.warning(
                                f"Skipping GIF upload for evaluation_id={evaluation_id}: invalid payload",
                                ColoredLogger.YELLOW,
                            )
                            continue
                        try:
                            await self.iwap_client.upload_evaluation_gif(evaluation_id, gif_bytes)
                            uploaded += 1
                        except Exception as gif_exc:
                            ColoredLogger.error(
                                f"Failed GIF upload for evaluation_id={evaluation_id}: {gif_exc}",
                                ColoredLogger.RED,
                            )
                    ColoredLogger.info(
                        f"GIF upload summary for agent {agent_uid}: uploaded={uploaded} skipped={skipped} total={len(pending_gif_uploads)}",
                        ColoredLogger.CYAN,
                    )
                    # Upload GIFs to Hippius S3 (independent, non-blocking)
                    try:
                        from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_gif_async

                        for evaluation_id, gif_payload, gif_task_id in pending_gif_uploads:
                            gif_bytes = extract_gif_bytes(gif_payload)
                            if gif_bytes:
                                await upload_evaluation_gif_async(
                                    round_id=self.current_round_id,
                                    validator_uid=int(self.uid),
                                    miner_uid=agent_uid,
                                    gif_data=gif_bytes,
                                    task_id=gif_task_id,
                                )
                    except Exception as s3_exc:  # noqa: BLE001
                        ColoredLogger.debug(f"Hippius S3 GIF upload failed (non-critical): {s3_exc}")
                return created > 0
            except Exception as e:
                ColoredLogger.error(f"Failed to submit batch: {e}", ColoredLogger.RED)
                raise

        return False
