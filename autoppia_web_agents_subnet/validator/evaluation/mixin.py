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

        # Capture which uids are pending (re-)evaluation so early-stop does not
        # rely on stale scores for miners whose submissions are being updated.
        uids_pending_eval: set[int] = set()
        try:
            q = getattr(getattr(self, "agents_queue", None), "queue", None)
            if q is not None:
                for item in list(q):
                    uid = getattr(item, "uid", None)
                    if isinstance(uid, int):
                        uids_pending_eval.add(uid)
        except Exception:
            uids_pending_eval = set()

        # Track best known score among already-evaluated miners so we can
        # early-stop miners that cannot possibly win (WTA settlement).
        best_score_so_far = 0.0
        try:
            agents_dict = getattr(self, "agents_dict", None)
            if isinstance(agents_dict, dict) and agents_dict:
                for info in agents_dict.values():
                    if not getattr(info, "evaluated", False):
                        continue
                    uid = getattr(info, "uid", None)
                    if isinstance(uid, int) and uid in uids_pending_eval:
                        continue
                    try:
                        score = float(getattr(info, "score", 0.0) or 0.0)
                    except Exception:
                        score = 0.0
                    if score > best_score_so_far:
                        best_score_so_far = score
        except Exception:
            best_score_so_far = 0.0

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

        def _finalize_agent(agent: object, *, score: float) -> None:
            """
            Mark an AgentInfo-like object as evaluated and persist it in agents_dict.
            """
            try:
                agent.score = float(score)  # type: ignore[attr-defined]
            except Exception:
                try:
                    agent.score = 0.0  # type: ignore[attr-defined]
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

        agents_evaluated = 0
        while not self.agents_queue.empty():
            # Refresh block each loop iteration so settlement cutoff checks don't drift.
            current_block = self.block
            wait_info = self.round_manager.get_wait_info(current_block)
            max_eval = float(getattr(validator_config, "MAXIMUM_EVALUATION_TIME", 0.0) or 0.0)
            max_consensus = float(getattr(validator_config, "MAXIMUM_CONSENSUS_TIME", 0.0) or 0.0)
            if wait_info["minutes_to_settlement"] < (max_eval + max_consensus):
                ColoredLogger.info("Stopping evaluation phase for settlement", ColoredLogger.YELLOW)
                return agents_evaluated

            agent = self.agents_queue.get()

            agent_instance = None
            # Pre-validate GitHub URL to avoid expensive docker/git work for
            # obviously invalid miner submissions.
            raw_github_url = getattr(agent, "github_url", None)
            require_ref = bool(getattr(validator_config, "REQUIRE_MINER_GITHUB_REF", False))
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
                    _finalize_agent(agent, score=0.0)
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
                        _finalize_agent(agent, score=0.0)
                        continue
                else:
                    if require_ref and not ref:
                        ColoredLogger.warning(
                            f"Skipping agent {getattr(agent, 'uid', '?')}: missing required ref in github_url={raw_s}",
                            ColoredLogger.YELLOW,
                        )
                        _finalize_agent(agent, score=0.0)
                        continue
                    if ref and resolve_remote_ref_commit(str(normalized_url), str(ref)) is None:
                        ColoredLogger.warning(
                            f"Skipping agent {getattr(agent, 'uid', '?')}: git ls-remote failed for ref={ref}",
                            ColoredLogger.YELLOW,
                        )
                        _finalize_agent(agent, score=0.0)
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
            batch_size = int(getattr(validator_config, "CONCURRENT_EVALUATION_NUM", 1) or 1)
            max_steps = int(getattr(validator_config, "AGENT_MAX_STEPS", 30) or 30)
            screening = int(getattr(validator_config, "SCREENING_TASKS_FOR_EARLY_STOP", 0) or 0)
            early_stop_behind_best = bool(getattr(validator_config, "EARLY_STOP_BEHIND_BEST", False))

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
                                f"[ACTIONS] task_id={task_item.task.id} uid={agent.uid} actions={len(action_list)} types={action_types}",
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
                                f"[EXEC_ACTIONS] task_id={task_item.task.id} uid={agent.uid} exec_actions={len(exec_types)} types={exec_types} last_url={last_url}",
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
                            }
                        )

                    # Submit batch evaluations to IWAP
                    if batch_eval_data:
                        try:
                            await self._submit_batch_evaluations_to_iwap(
                                agent_uid=agent.uid,
                                batch_eval_data=batch_eval_data,
                            )
                            ColoredLogger.info(
                                f"✅ Submitted {len(batch_eval_data)} evaluations to IWAP for agent {agent.uid}",
                                ColoredLogger.GREEN,
                            )
                        except Exception as e:
                            ColoredLogger.error(
                                f"Failed to submit batch evaluations to IWAP for agent {agent.uid}: {e}",
                                ColoredLogger.RED,
                            )

                    if screening and len(rewards) >= screening and sum(rewards) == 0.0:
                        ColoredLogger.warning(
                            f"Agent {agent.uid} is failing first {len(rewards)} tasks, stopping evaluation",
                            ColoredLogger.YELLOW,
                        )
                        break

                    # WTA early stop: if even perfect rewards on remaining tasks cannot
                    # beat the current best, abort to save time/cost.
                    if early_stop_behind_best and total_tasks > 0:
                        tasks_done = min(i + len(batch_tasks), total_tasks)
                        upper_bound_avg = (sum(rewards) + float(total_tasks - tasks_done)) / float(total_tasks)
                        if upper_bound_avg < best_score_so_far:
                            ColoredLogger.warning(
                                f"Agent {agent.uid} cannot beat best_score={best_score_so_far:.4f} (upper_bound={upper_bound_avg:.4f} after {tasks_done}/{total_tasks} tasks); stopping evaluation",
                                ColoredLogger.YELLOW,
                            )
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
            avg_reward = (sum(rewards) / float(total_tasks)) if total_tasks > 0 else 0.0
            _finalize_agent(agent, score=float(avg_reward))
            agents_evaluated += 1
            if agent.score > best_score_so_far:
                best_score_so_far = float(agent.score)

        ColoredLogger.info("Evaluation phase completed", ColoredLogger.MAGENTA)
        return agents_evaluated

    async def _submit_batch_evaluations_to_iwap(
        self,
        *,
        agent_uid: int,
        batch_eval_data: list,
    ) -> None:
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
            return

        if not hasattr(self, "current_agent_runs") or agent_uid not in self.current_agent_runs:
            ColoredLogger.warning(f"No agent run found for agent {agent_uid}, skipping IWAP submission", ColoredLogger.YELLOW)
            return

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

            def _preview_indices(n: int, limit: int = 6):
                if n <= limit:
                    return list(range(n))
                head = list(range(3))
                tail = list(range(max(0, n - 3), n))
                return head + tail

            def _fmt_action_line(a_dict):
                if not isinstance(a_dict, dict):
                    return str(a_dict)
                t = a_dict.get("type")
                url = a_dict.get("url")
                text = a_dict.get("text")
                sel = a_dict.get("selector")
                # Keep logs grep-friendly and bounded.
                if isinstance(text, str) and len(text) > 80:
                    text = text[:80] + "…"
                return f"type={t} url={url} selector={sel} text={text}"

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
                    f"[IWAP_ACTIONS] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} actions={len(actions)} types={action_types}",
                    ColoredLogger.CYAN,
                )

                # Log a bounded preview of the actual action objects being sent to IWAP.
                idxs = _preview_indices(len(actions))
                for i in idxs:
                    a = actions[i]
                    ColoredLogger.info(
                        f"[IWAP_ACTION] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} i={i} {_fmt_action_line(a)}",
                        ColoredLogger.CYAN,
                    )
            except Exception:
                pass

            # Always emit a bounded preview of the actions the evaluator actually executed.
            try:
                idxs = _preview_indices(len(exec_actions))
                for i in idxs:
                    ColoredLogger.info(
                        f"[EXEC_ACTION] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} i={i} {_fmt_action_line(exec_actions[i])}",
                        ColoredLogger.CYAN,
                    )
            except Exception:
                pass

            # Optional: upload task execution log for S3-backed storage (batch path)
            try:
                from autoppia_web_agents_subnet.validator.config import UPLOAD_TASK_LOGS
            except Exception:
                UPLOAD_TASK_LOGS = False
            if UPLOAD_TASK_LOGS and getattr(self, "iwap_client", None):
                try:
                    from autoppia_web_agents_subnet.platform.utils.task_flow import _build_task_log_payload

                    task_log_payload = _build_task_log_payload(
                        task_payload=task_payload,
                        agent_run=agent_run,
                        miner_uid=agent_uid,
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
                        last_type = None
                        s3_actions = []
                        if isinstance(steps, list) and steps:
                            ao = steps[-1].get("agent_output") if isinstance(steps[-1], dict) else None
                            act = ao.get("action") if isinstance(ao, dict) else None
                            if isinstance(act, dict):
                                last_type = act.get("type")
                            # Collect actions for mismatch/debug preview.
                            for step in steps:
                                if not isinstance(step, dict):
                                    continue
                                ao = step.get("agent_output")
                                if not isinstance(ao, dict):
                                    continue
                                act = ao.get("action")
                                if isinstance(act, dict):
                                    s3_actions.append(act)
                        ColoredLogger.info(
                            f"[S3_ACTIONS] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} steps={len(steps) if isinstance(steps, list) else 0} last_action={last_type}",
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
                                for i in _preview_indices(exec_n):
                                    ColoredLogger.info(
                                        f"[EXEC_ACTION] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} i={i} {_fmt_action_line(exec_actions[i])}",
                                        ColoredLogger.CYAN,
                                    )
                                for i in _preview_indices(iwap_n):
                                    ColoredLogger.info(
                                        f"[IWAP_ACTION] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} i={i} {_fmt_action_line(actions[i])}",
                                        ColoredLogger.CYAN,
                                    )
                                for i in _preview_indices(s3_n):
                                    ColoredLogger.info(
                                        f"[S3_ACTION] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} i={i} {_fmt_action_line(s3_actions[i])}",
                                        ColoredLogger.CYAN,
                                    )
                            else:
                                # Still log the executed action summary for correlation when everything matches.
                                ColoredLogger.info(
                                    f"[EXEC_ACTIONS] task_id={full_task_id} agent_run_id={agent_run.agent_run_id} exec_actions={exec_n}",
                                    ColoredLogger.CYAN,
                                )
                        except Exception:
                            pass
                    except Exception:
                        pass
                    await self.iwap_client.upload_task_log(task_log_payload)
                except Exception as log_exc:  # noqa: BLE001
                    ColoredLogger.warning(
                        f"Task log upload failed for task_id={getattr(task_payload, 'task_id', None)} miner_uid={agent_uid}: {log_exc}",
                        ColoredLogger.YELLOW,
                    )
            gif_payload = evaluation_meta_dict.get("gif_recording")
            evaluation_result = evaluation_payload.get("evaluation_result", {})
            evaluation_id = evaluation_result.get("evaluation_id") if isinstance(evaluation_result, dict) else None
            if evaluation_id and gif_payload:
                pending_gif_uploads.append((str(evaluation_id), gif_payload))

        if not evaluations_batch:
            ColoredLogger.warning("No evaluations to submit in batch", ColoredLogger.YELLOW)
            return

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
                    for evaluation_id, gif_payload in pending_gif_uploads:
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
            except Exception as e:
                ColoredLogger.error(f"Failed to submit batch: {e}", ColoredLogger.RED)
                raise
