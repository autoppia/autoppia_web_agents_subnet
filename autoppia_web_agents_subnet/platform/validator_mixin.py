from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

import bittensor as bt

from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.config import (
    IWAP_API_BASE_URL,
    IWAP_VALIDATOR_AUTH_MESSAGE,
    ENABLE_CHECKPOINT_SYSTEM,
)
from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform import main as iwa_main
from autoppia_web_agents_subnet.platform.state_manager import RoundStateManager

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
)
from autoppia_web_agents_subnet.platform.utils.task_flow import (
    submit_task_results as _utils_submit_task_results,
)


class ValidatorPlatformMixin:
    """Shared IWAP integration helpers extracted from the validator loop."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._IWAP_VALIDATOR_AUTH_MESSAGE = IWAP_VALIDATOR_AUTH_MESSAGE or "I am a honest validator"
        self._auth_warning_emitted = False
        self.iwap_client = iwa_main.IWAPClient(
            base_url=IWAP_API_BASE_URL,
            auth_provider=self._build_iwap_auth_headers,
        )
        self.current_round_id: Optional[str] = None
        self.current_round_tasks: Dict[str, iwa_models.TaskIWAP] = {}
        self.current_agent_runs: Dict[int, iwa_models.AgentRunIWAP] = {}
        self.current_miner_snapshots: Dict[int, iwa_models.MinerSnapshotIWAP] = {}
        self.round_handshake_payloads: Dict[int, Any] = {}
        self.round_start_timestamp: float = 0.0
        self.agent_run_accumulators: Dict[int, Dict[str, float]] = {}
        # Track completed (miner_uid, task_id) to avoid duplicates on resume
        self._completed_pairs: Set[Tuple[int, str]] = set()
        # Last resume decision details for diagnostics
        self._last_resume_info: Dict[str, Any] = {"status": "init", "reason": ""}
        # Saved evaluation records to rebuild accumulators on resume
        self._eval_records: List[Dict[str, Any]] = []
        # Phase flags for IWAP steps (p1=start_round, p2=set_tasks)
        self._phases: Dict[str, Any] = {"p1_done": False, "p2_done": False}
        # Pickle-based checkpoint manager
        self.state_manager = RoundStateManager(self)

    def _log_iwap_phase(self, phase: str, message: str, *, level: str = "info", exc_info: bool = False) -> None:
        # Delegate to logging utility (keeps test compatibility with monkeypatching this method)
        log_iwap_phase(phase, message, level=level, exc_info=exc_info)

    def _generate_validator_round_id(self, *, current_block: int) -> str:
        """
        Generate a unique validator round ID with round number.

        Calculates round number via round_manager.calculate_round(current_block).
        """
        round_number: Optional[int] = None
        try:
            rm = getattr(self, "round_manager", None)
            if rm is not None and getattr(rm, "ROUND_BLOCK_LENGTH", 0):
                base_block = getattr(rm, "minimum_start_block", 0) or 0
                if current_block <= base_block:
                    round_number = 0
                else:
                    blocks_since_start = current_block - base_block
                    round_index = blocks_since_start // rm.ROUND_BLOCK_LENGTH
                    round_number = int(round_index + 1)
        except Exception as e:  # noqa: BLE001
            bt.logging.debug(f"Could not calculate round number: {e}")
            round_number = None

        return iwa_main.generate_validator_round_id(round_number=round_number)

    def _build_iwap_auth_headers(self) -> Dict[str, str]:
        hotkey = getattr(self.wallet.hotkey, "ss58_address", None)
        if not hotkey:
            raise RuntimeError("Validator hotkey is unavailable for IWAP authentication")

        message = self._IWAP_VALIDATOR_AUTH_MESSAGE
        if not message:
            if not self._auth_warning_emitted:
                self._log_iwap_phase(
                    "Auth",
                    "Validator auth message not configured; IWAP requests will not be signed",
                    level="warning",
                )
                self._auth_warning_emitted = True
            return {}

        try:
            return build_iwap_auth_headers(self.wallet, message)
        except Exception as exc:
            self._log_iwap_phase(
                "Auth",
                f"Failed to sign IWAP auth message: {exc}",
                level="error",
                exc_info=True,
            )
            raise

    def _build_validator_identity(self) -> iwa_models.ValidatorIdentityIWAP:
        return _utils_build_validator_identity(self)

    # ──────────────────────────────────────────────────────────────────────────
    # Crash-resume helpers now routed to RoundStateManager
    # ──────────────────────────────────────────────────────────────────────────

    def _save_round_state(self, *, tasks: Optional[List[TaskWithProject]] = None) -> None:
        # Wrapper to new checkpoint manager
        if not ENABLE_CHECKPOINT_SYSTEM:
            # Do not persist checkpoints when system is disabled
            bt.logging.debug("Checkpoint save skipped: checkpoint system disabled")
            return
        try:
            self.state_manager.save_checkpoint(tasks=tasks)
        except Exception as exc:
            bt.logging.warning(f"Failed to persist checkpoint: {exc}")

    def _load_round_state(self, *, current_block: Optional[int] = None) -> Optional[Dict[str, Any]]:
        # Wrapper to new checkpoint manager; returns a JSON-like shim for call sites
        if not ENABLE_CHECKPOINT_SYSTEM:
            # Checkpoint system disabled - always start fresh rounds
            self._last_resume_info = {"status": "disabled", "reason": "checkpoint system disabled"}
            bt.logging.info("Resume disabled by config (ENABLE_CHECKPOINT_SYSTEM=false); starting fresh")
            return None
        ckpt = self.state_manager.load_checkpoint()
        if ckpt is None:
            self._last_resume_info = {"status": "skipped", "reason": "checkpoint not found"}
            return None

        # If the stored round is no longer the active round on-chain, discard it.
        rm = getattr(self, "round_manager", None)
        try:
            if (
                current_block is not None
                and rm is not None
                and getattr(rm, "ROUND_BLOCK_LENGTH", 0)
                and getattr(ckpt, "rm_start_block", None) is not None
            ):
                round_length = int(getattr(rm, "ROUND_BLOCK_LENGTH", 0)) or 0
                base_block = int(getattr(rm, "minimum_start_block", 0) or 0)

                def _round_for_block(block: int) -> int:
                    if block <= base_block:
                        return 0
                    return int(((block - base_block) // round_length) + 1)

                checkpoint_round = _round_for_block(int(ckpt.rm_start_block))
                current_round = _round_for_block(int(current_block))

                if checkpoint_round != current_round:
                    bt.logging.warning(
                        f"State checkpoint discarded: stored round {checkpoint_round} (start_block={ckpt.rm_start_block}) "
                        f"!= current round {current_round} (block={current_block})"
                    )
                    try:
                        self._reset_iwap_round_state()
                    except Exception:
                        pass
                    reset_consensus = getattr(self, "_reset_consensus_state", None)
                    if callable(reset_consensus):
                        try:
                            reset_consensus()
                        except Exception:
                            pass
                    try:
                        self.state_manager.cleanup()
                    except Exception:
                        pass
                    self._last_resume_info = {
                        "status": "discarded",
                        "reason": "stale_round",
                        "checkpoint_round": checkpoint_round,
                        "current_round": current_round,
                    }
                    return None
        except Exception as exc:  # pragma: no cover - defensive logging
            bt.logging.warning(f"Checkpoint round validation failed: {exc}")

        self._last_resume_info = {
            "status": "loaded",
            "reason": "checkpoint loaded",
            "tasks_in_file": len(ckpt.all_tasks or []),
            "active_miners": len(getattr(self, "active_miner_uids", []) or []),
            "agent_runs": len(getattr(self, "current_agent_runs", {}) or {}),
            "completed_pairs": len(getattr(self, "_completed_pairs", set()) or set()),
        }
        return {"validator_round_id": ckpt.validator_round_id}

    # moved to RoundPhaseValidatorMixin

    def _remove_round_state(self) -> None:
        # Wrapper to new checkpoint manager
        try:
            self.state_manager.cleanup()
        except Exception:
            pass

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
    ) -> None:
        await _utils_finish_round_flow(
            self,
            avg_rewards=avg_rewards,
            final_weights=final_weights,
            tasks_completed=tasks_completed,
        )

    def _reset_iwap_round_state(self) -> None:
        self.current_round_id = None
        self.current_round_tasks = {}
        self.current_agent_runs = {}
        self.current_miner_snapshots = {}
        self.round_handshake_payloads = {}
        self.round_start_timestamp = 0.0
        self.agent_run_accumulators = {}
        self._completed_pairs = set()
        self._phases = {"p1_done": False, "p2_done": False}
        reset_consensus = getattr(self, "_reset_consensus_state", None)
        if callable(reset_consensus):
            try:
                reset_consensus()
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
        try:
            existing = getattr(self, "async_subtensor", None) or getattr(self, "_async_subtensor", None)
            if existing is not None:
                return existing
        except Exception:
            pass

        # Lazy-create and cache
        try:
            from bittensor import AsyncSubtensor  # type: ignore
        except Exception as e:
            bt.logging.warning(f"AsyncSubtensor import failed: {e}")
            raise

        network = None
        try:
            network = self.config.subtensor.network
        except Exception:
            network = None

        st = None
        try:
            # Avoid chain_endpoint argument for broad compatibility
            st = AsyncSubtensor(network=network)  # type: ignore[arg-type]
        except Exception:
            st = AsyncSubtensor()  # type: ignore[call-arg]

        # Initialize if supported
        try:
            init = getattr(st, "initialize", None)
            if callable(init):
                await init()
        except Exception:
            pass

        try:
            self._async_subtensor = st
        except Exception:
            pass
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
            substrate = getattr(async_subtensor, 'substrate', None)
            if substrate is not None:
                bt.logging.debug("Found substrate interface")

                # Step 2: Access the websocket connection
                websocket = getattr(substrate, 'websocket', None)
                if websocket is not None:
                    bt.logging.debug("Found websocket connection, cancelling background tasks...")

                    # Step 3: Cancel all websocket background tasks
                    task_attrs = ['_sending_task', '_receiving_task', '_start_sending', '_ws_send_task']
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
                        if hasattr(websocket, 'close') and callable(websocket.close):
                            await websocket.close()
                            bt.logging.debug("Websocket closed")
                    except Exception as e:
                        bt.logging.debug(f"Websocket close error: {e}")

                # Step 5: Close the substrate interface
                try:
                    if hasattr(substrate, 'close') and callable(substrate.close):
                        await substrate.close()
                        bt.logging.debug("Substrate interface closed")
                except Exception as e:
                    bt.logging.debug(f"Substrate close error: {e}")

            # Step 6: Try high-level close methods
            try:
                if hasattr(async_subtensor, 'close') and callable(async_subtensor.close):
                    await async_subtensor.close()
                    bt.logging.debug("AsyncSubtensor.close() called")
                elif hasattr(async_subtensor, 'disconnect') and callable(async_subtensor.disconnect):
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
