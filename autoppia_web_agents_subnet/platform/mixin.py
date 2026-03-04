from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import bittensor as bt

from autoppia_web_agents_subnet.validator.config import (
    IWAP_API_BASE_URL,
    IWAP_VALIDATOR_AUTH_MESSAGE,
)
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform import client as iwa_main

from autoppia_web_agents_subnet.platform.utils.iwa_core import (
    log_iwap_phase,
    build_iwap_auth_headers,
    metagraph_numeric as _metrics_metagraph_numeric,
    normalized_stake_tao as _metrics_normalized_stake_tao,
    validator_vtrust as _metrics_validator_vtrust,
    build_validator_identity as _utils_build_validator_identity,
    build_validator_snapshot as _utils_build_validator_snapshot,
    build_iwap_tasks as _utils_build_iwap_tasks,
    extract_gif_bytes as _utils_extract_gif_bytes,
)
from autoppia_web_agents_subnet.platform.utils.round_flow import (
    start_round_flow as _utils_start_round_flow,
    finish_round_flow as _utils_finish_round_flow,
    register_participating_miners_in_iwap as _utils_register_participating_miners_in_iwap,
)
from autoppia_web_agents_subnet.platform.utils.task_flow import (
    submit_task_results as _utils_submit_task_results,
)


class ValidatorPlatformMixin:
    """Shared IWAP integration helpers extracted from the validator loop."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Unify all validator local artifacts under the bittensor neuron path tree.
        # This avoids splitting state between repo ./data and ~/.bittensor/...
        try:
            default_backup_dir = Path(str(self.config.neuron.full_path)).parent.parent / "data"
        except Exception:
            default_backup_dir = Path("data")
        os.environ.setdefault("IWAP_BACKUP_DIR", str(default_backup_dir))
        backup_dir = Path(os.environ.get("IWAP_BACKUP_DIR", str(default_backup_dir)))
        self._IWAP_VALIDATOR_AUTH_MESSAGE = IWAP_VALIDATOR_AUTH_MESSAGE or "I am a honest validator"
        self._auth_warning_emitted = False
        self.iwap_client = iwa_main.IWAPClient(
            base_url=IWAP_API_BASE_URL,
            backup_dir=backup_dir,
            auth_provider=self._build_iwap_auth_headers,
        )
        self.current_round_id: Optional[str] = None
        self.current_round_tasks: Dict[str, iwa_models.TaskIWAP] = {}
        self.current_agent_runs: Dict[int, iwa_models.AgentRunIWAP] = {}
        self.current_miner_snapshots: Dict[int, iwa_models.MinerSnapshotIWAP] = {}
        self._iwap_shadow_mode = False
        self.round_handshake_payloads: Dict[int, Any] = {}
        self.round_start_timestamp: float = 0.0
        self.agent_run_accumulators: Dict[int, Dict[str, float]] = {}
        # (repo, commit) already evaluated per miner -> agent_run_id + stats (no re-eval on resubmit)
        self._evaluated_commits_by_miner: Dict[int, Dict[str, Dict[str, Any]]] = {}  # uid -> "repo|commit" -> {agent_run_id, ...stats}
        # Set during handshake when reusing a past run (same commit evaluated in a previous round)
        self.reused_from_agent_run_id_by_uid: Dict[int, str] = {}
        self.reused_stats_by_uid: Dict[int, Dict[str, Any]] = {}
        # Track completed (miner_uid, task_id) to avoid duplicates
        self._completed_pairs: Set[Tuple[int, str]] = set()
        # Phase flags for IWAP steps (p1=start_round, p2=set_tasks)
        self._phases: Dict[str, Any] = {"p1_done": False, "p2_done": False}

    def _log_iwap_phase(self, phase: str, message: str, *, level: str = "info", exc_info: bool = False) -> None:
        # Delegate to logging utility (keeps test compatibility with monkeypatching this method)
        log_iwap_phase(phase, message, level=level, exc_info=exc_info)

    def _generate_validator_round_id(self, *, current_block: int) -> str:
        """
        Generate a unique validator round ID with season and round information.

        Format: validator_round_{season}_{round_in_season}_{hash}
        Example: validator_round_4_6_abc123def456
        """
        rm = getattr(self, "round_manager", None)
        if rm is None or not getattr(rm, "round_block_length", 0):
            raise RuntimeError("Round manager is not initialized; cannot derive validator round id")

        round_length = int(rm.round_block_length)
        if round_length <= 0:
            raise RuntimeError("round_block_length must be a positive integer")

        # Calculate season and round within season
        season_number = iwa_main.compute_season_number(current_block)
        round_number_in_season = iwa_main.compute_round_number_in_season(current_block, round_length)

        return iwa_main.generate_validator_round_id(season_number=season_number, round_number_in_season=round_number_in_season)

    def _build_iwap_auth_headers(self) -> Dict[str, str]:
        hotkey = getattr(self.wallet.hotkey, "ss58_address", None)
        if not hotkey:
            raise RuntimeError("Validator hotkey is unavailable for IWAP authentication")

        message = self._IWAP_VALIDATOR_AUTH_MESSAGE
        if not message:
            self._log_iwap_phase(
                "Auth",
                "Validator auth message not configured; aborting IWAP request signing",
                level="error",
            )
            raise RuntimeError("Validator auth message not configured; cannot sign IWAP requests")

        return build_iwap_auth_headers(self.wallet, message)

    def _build_validator_identity(self) -> iwa_models.ValidatorIdentityIWAP:
        return _utils_build_validator_identity(self)

    def _metagraph_numeric(self, attribute: str, uid: int) -> Optional[float]:
        return _metrics_metagraph_numeric(self.metagraph, attribute, uid)

    def _normalized_stake_tao(self, uid: int) -> Optional[float]:
        return _metrics_normalized_stake_tao(self.metagraph, uid)

    def _validator_vtrust(self, uid: int) -> Optional[float]:
        return _metrics_validator_vtrust(self.metagraph, uid)

    def _build_validator_snapshot(self, validator_round_id: str) -> iwa_models.ValidatorSnapshotIWAP:
        return _utils_build_validator_snapshot(self, validator_round_id)

    def _build_iwap_tasks(
        self,
        *,
        validator_round_id: str,
        tasks: List[TaskWithProject],
    ) -> Dict[str, iwa_models.TaskIWAP]:
        return _utils_build_iwap_tasks(validator_round_id=validator_round_id, tasks=tasks)

    async def _iwap_start_round(self, *, current_block: int, n_tasks: int) -> None:
        await _utils_start_round_flow(self, current_block=current_block, n_tasks=n_tasks)

    async def _iwap_register_miners(self) -> None:
        """
        Register all participating miners in IWAP dashboard after handshake.

        Creates records for each miner that responded to handshake:
        - validator_round_miners (miner identity and snapshot)
        - miner_evaluation_runs (agent run for this round)
        """
        await _utils_register_participating_miners_in_iwap(self)

    async def _iwap_submit_task_results(
        self,
        *,
        task_item: TaskWithProject,
        task_solutions,
        eval_scores,
        test_results_list,
        evaluation_results,
        execution_times,
        rewards: List[float],
    ) -> None:
        await _utils_submit_task_results(
            self,
            task_item=task_item,
            task_solutions=task_solutions,
            eval_scores=eval_scores,
            test_results_list=test_results_list,
            evaluation_results=evaluation_results,
            execution_times=execution_times,
            rewards=rewards,
        )

    @staticmethod
    def _extract_gif_bytes(payload: Optional[object]) -> Optional[bytes]:
        return _utils_extract_gif_bytes(payload)

    async def _finish_iwap_round(
        self,
        *,
        avg_rewards: Dict[int, float],
        final_weights: Dict[int, float],
        tasks_completed: int,
    ) -> bool:
        return await _utils_finish_round_flow(
            self,
            avg_rewards=avg_rewards,
            final_weights=final_weights,
            tasks_completed=tasks_completed,
        )

    def _iwap_prev_round_path(self) -> Path:
        """Path to persist prev_round_agent_run_ids / prev_round_run_stats so is_reused survives validator restart."""
        try:
            full_path = Path(str(getattr(self, "config", None) and getattr(self.config, "neuron", None) and getattr(self.config.neuron, "full_path", None) or "."))
        except Exception:
            full_path = Path(".")
        full_path.mkdir(parents=True, exist_ok=True)
        return full_path / "iwap_prev_round.json"

    def _save_iwap_prev_round_state(self) -> None:
        """Persist prev_round_agent_run_ids, prev_round_run_stats and _evaluated_commits_by_miner to disk (best-effort)."""
        try:
            run_ids = getattr(self, "prev_round_agent_run_ids", None) or {}
            stats = getattr(self, "prev_round_run_stats", None) or {}
            evaluated = getattr(self, "_evaluated_commits_by_miner", None) or {}
            if not run_ids and not stats and not evaluated:
                return
            path = self._iwap_prev_round_path()
            # Serialize _evaluated_commits_by_miner: uid -> {"repo|commit": stats_dict}
            evaluated_ser = {}
            for uid, key_to_data in evaluated.items():
                evaluated_ser[str(uid)] = dict(key_to_data)
            data = {
                "prev_round_agent_run_ids": {str(uid): run_id for uid, run_id in run_ids.items()},
                "prev_round_run_stats": {str(uid): s for uid, s in stats.items()},
                "evaluated_commits_by_miner": evaluated_ser,
            }
            path.write_text(json.dumps(data, indent=0), encoding="utf-8")
        except Exception:
            pass

    def _load_iwap_prev_round_state(self) -> None:
        """Load prev_round_agent_run_ids, prev_round_run_stats and _evaluated_commits_by_miner from disk so is_reused works after restart."""
        try:
            path = self._iwap_prev_round_path()
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            run_ids_raw = data.get("prev_round_agent_run_ids") or {}
            stats_raw = data.get("prev_round_run_stats") or {}
            self.prev_round_agent_run_ids = {int(uid): run_id for uid, run_id in run_ids_raw.items()}
            self.prev_round_run_stats = {int(uid): s for uid, s in stats_raw.items()}
            evaluated_raw = data.get("evaluated_commits_by_miner") or {}
            self._evaluated_commits_by_miner = {int(uid): dict(key_to_data) for uid, key_to_data in evaluated_raw.items()}
        except Exception:
            self.prev_round_agent_run_ids = getattr(self, "prev_round_agent_run_ids", None) or {}
            self.prev_round_run_stats = getattr(self, "prev_round_run_stats", None) or {}
            self._evaluated_commits_by_miner = getattr(self, "_evaluated_commits_by_miner", None) or {}

    def _reset_iwap_round_state(self) -> None:
        # Persist current runs/stats for next round (reused-run resolution).
        # Only snapshot when we have runs (first caller, e.g. finish_round_flow); if called again
        # from settlement after current_agent_runs was already cleared, do not overwrite prev_round_* with empty.
        current_runs = getattr(self, "current_agent_runs", None) or {}
        if current_runs:
            self.prev_round_agent_run_ids = {uid: run.agent_run_id for uid, run in current_runs.items()}
            self.prev_round_run_stats = {}
            for uid, run in current_runs.items():
                acc = getattr(self, "agent_run_accumulators", {}).get(uid, {})
                tasks = int(acc.get("tasks", 0) or 0)
                reward_sum = float(acc.get("reward", 0.0) or 0.0)
                eval_sum = float(acc.get("eval_score", 0.0) or 0.0)
                time_sum = float(acc.get("execution_time", 0.0) or 0.0)
                avg_score = (eval_sum / tasks) if tasks else (getattr(run, "average_score", None) or 0.0)
                avg_reward = (reward_sum / tasks) if tasks else (getattr(run, "average_reward", None) or 0.0)
                avg_time = (time_sum / tasks) if tasks else (getattr(run, "average_execution_time", None) or 0.0)
                round_rewards = getattr(getattr(self, "round_manager", None), "round_rewards", {}) or {}
                miner_rewards = round_rewards.get(uid, []) or []
                success_tasks = len([r for r in miner_rewards if float(r) >= 0.5])
                agent_for_uid = getattr(self, "agents_dict", {}).get(uid)
                self.prev_round_run_stats[uid] = {
                    "agent_run_id": run.agent_run_id,
                    "average_score": avg_score,
                    "average_reward": avg_reward,
                    "average_execution_time": avg_time,
                    "total_tasks": tasks or len(miner_rewards),
                    "success_tasks": success_tasks,
                    "failed_tasks": (tasks or len(miner_rewards)) - success_tasks,
                    "zero_reason": getattr(agent_for_uid, "zero_reason", None) if agent_for_uid else None,
                }
        self.current_round_id = None
        self.current_round_tasks = {}
        self.current_agent_runs = {}
        self.current_miner_snapshots = {}
        self.round_handshake_payloads = {}
        self.round_start_timestamp = 0.0
        self.agent_run_accumulators = {}
        self._completed_pairs = set()
        self._phases = {"p1_done": False, "p2_done": False}
        self.reused_from_agent_run_id_by_uid = {}
        self.reused_stats_by_uid = {}
        self._s3_task_log_urls = []
        self._iwap_shadow_mode = False
        try:
            from autoppia_web_agents_subnet.utils.logging import ColoredLogger

            ColoredLogger.clear_round_log_file()
        except Exception:
            pass
        # Reset round number to force recalculation on next round start
        # This prevents reusing stale values when discarding old round state
        self._current_round_number = None

        # Persist prev_round so after validator restart we still send is_reused/reused_from_agent_run_id
        self._save_iwap_prev_round_state()

    def _register_evaluated_commit(
        self,
        uid: int,
        normalized_repo: str,
        commit_sha: str,
        agent_run_id: str,
        stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record that we evaluated (repo, commit) for this miner so we don't re-evaluate on resubmit."""
        if not normalized_repo or not commit_sha or not agent_run_id:
            return
        key = f"{normalized_repo.strip()}|{commit_sha.strip()}"
        if not isinstance(getattr(self, "_evaluated_commits_by_miner", None), dict):
            self._evaluated_commits_by_miner = {}
        existing = (self._evaluated_commits_by_miner.get(uid) or {}).get(key)
        incoming = {"agent_run_id": agent_run_id, **(stats or {})}
        # Keep explicit first/last evaluated round metadata per commit key.
        season_val = incoming.get("evaluated_season")
        round_val = incoming.get("evaluated_round")
        if season_val is not None and "last_evaluated_season" not in incoming:
            incoming["last_evaluated_season"] = season_val
        if round_val is not None and "last_evaluated_round" not in incoming:
            incoming["last_evaluated_round"] = round_val
        if season_val is not None and "first_evaluated_season" not in incoming:
            incoming["first_evaluated_season"] = season_val
        if round_val is not None and "first_evaluated_round" not in incoming:
            incoming["first_evaluated_round"] = round_val

        # Do not downgrade a good reusable source with an empty/incomplete run.
        # Keep first meaningful evaluated run as anchor for reuse.
        if isinstance(existing, dict):
            # Preserve first evaluation markers forever for this commit.
            if existing.get("first_evaluated_season") is not None:
                incoming["first_evaluated_season"] = existing.get("first_evaluated_season")
            if existing.get("first_evaluated_round") is not None:
                incoming["first_evaluated_round"] = existing.get("first_evaluated_round")
            try:
                existing_total = int(existing.get("total_tasks", 0) or 0)
            except Exception:
                existing_total = 0
            try:
                incoming_total = int(incoming.get("total_tasks", 0) or 0)
            except Exception:
                incoming_total = 0

            if existing_total > 0 and incoming_total <= 0:
                return
            if existing_total > 0 and incoming_total > 0:
                return
            if existing_total <= 0 and incoming_total > 0:
                self._evaluated_commits_by_miner.setdefault(uid, {})[key] = incoming
                try:
                    self._save_iwap_prev_round_state()
                except Exception:
                    pass
                return

        self._evaluated_commits_by_miner.setdefault(uid, {})[key] = incoming
        try:
            self._save_iwap_prev_round_state()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Async subtensor provider for consensus (single instance per validator)
    # ──────────────────────────────────────────────────────────────────────────
    async def _get_async_subtensor(self):
        """
        Return a shared AsyncSubtensor instance for this validator.

        - If an async subtensor is already attached (e.g., self.async_subtensor or cached), reuse it.
        - Otherwise, create one using safe constructor (without chain_endpoint), and initialize if needed.
        """
        # Reuse if already present on the instance (external init)
        existing = getattr(self, "async_subtensor", None) or getattr(self, "_async_subtensor", None)
        if existing is not None:
            return existing

        # Lazy-create and cache
        try:
            from bittensor import AsyncSubtensor  # type: ignore
        except Exception as e:
            bt.logging.warning(f"AsyncSubtensor import failed: {e}")
            raise

        network = getattr(getattr(self.config, "subtensor", None), "network", None)

        st = None
        try:
            # Avoid chain_endpoint argument for broad compatibility
            st = AsyncSubtensor(network=network)  # type: ignore[arg-type]
        except Exception:
            st = AsyncSubtensor()  # type: ignore[call-arg]

        # Initialize if supported
        init = getattr(st, "initialize", None)
        if callable(init):
            try:
                await init()
            except Exception as exc:  # noqa: BLE001
                bt.logging.warning(f"AsyncSubtensor initialize() failed: {exc}")

        self._async_subtensor = st
        return st

    async def _close_async_subtensor(self):
        """
        Properly close the AsyncSubtensor WebSocket connection to avoid pending tasks.
        This method handles the internal async_substrate_interface websocket cleanup.
        """
        import asyncio

        try:
            async_subtensor = getattr(self, "_async_subtensor", None) or getattr(self, "async_subtensor", None)
            if async_subtensor is None:
                return

            bt.logging.debug("Starting AsyncSubtensor cleanup...")

            # Step 1: Access the substrate interface
            substrate = getattr(async_subtensor, "substrate", None)
            if substrate is not None:
                bt.logging.debug("Found substrate interface")

                # Step 2: Access the websocket connection
                websocket = getattr(substrate, "websocket", None)
                if websocket is not None:
                    bt.logging.debug("Found websocket connection, cancelling background tasks...")

                    # Step 3: Cancel all websocket background tasks
                    task_attrs = ["_sending_task", "_receiving_task", "_start_sending", "_ws_send_task"]
                    for task_attr in task_attrs:
                        task = getattr(websocket, task_attr, None)
                        if task is not None and isinstance(task, asyncio.Task):
                            if not task.done():
                                bt.logging.debug(f"Cancelling {task_attr}...")
                                task.cancel()
                                try:
                                    await asyncio.wait_for(task, timeout=1.0)
                                except (asyncio.CancelledError, asyncio.TimeoutError):
                                    bt.logging.debug(f"{task_attr} cancelled/timeout")
                                except Exception as e:
                                    bt.logging.debug(f"{task_attr} cancel error: {e}")

                    # Step 4: Close the websocket
                    try:
                        if hasattr(websocket, "close") and callable(websocket.close):
                            await websocket.close()
                            bt.logging.debug("Websocket closed")
                    except Exception as e:
                        bt.logging.debug(f"Websocket close error: {e}")

                # Step 5: Close the substrate interface
                try:
                    if hasattr(substrate, "close") and callable(substrate.close):
                        await substrate.close()
                        bt.logging.debug("Substrate interface closed")
                except Exception as e:
                    bt.logging.debug(f"Substrate close error: {e}")

            # Step 6: Try high-level close methods
            try:
                if hasattr(async_subtensor, "close") and callable(async_subtensor.close):
                    await async_subtensor.close()
                    bt.logging.debug("AsyncSubtensor.close() called")
                elif hasattr(async_subtensor, "disconnect") and callable(async_subtensor.disconnect):
                    await async_subtensor.disconnect()
                    bt.logging.debug("AsyncSubtensor.disconnect() called")
            except Exception as e:
                bt.logging.debug(f"High-level close error: {e}")

            # Step 7: Small delay to allow cleanup
            await asyncio.sleep(0.1)

            bt.logging.debug("AsyncSubtensor cleanup complete")

        except Exception as e:
            bt.logging.debug(f"Error during AsyncSubtensor cleanup: {e}")
        finally:
            # Always clear the reference
            try:
                if hasattr(self, "_async_subtensor"):
                    self._async_subtensor = None
                if hasattr(self, "async_subtensor"):
                    self.async_subtensor = None
            except Exception:
                pass
