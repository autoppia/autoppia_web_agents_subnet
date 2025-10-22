from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

import bittensor as bt

from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.config import (
    IWAP_API_BASE_URL,
    VALIDATOR_AUTH_MESSAGE,
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
from autoppia_web_agents_subnet.platform.utils.iwa_flow import (
    start_round_flow as _utils_start_round_flow,
    finish_round_flow as _utils_finish_round_flow,
    submit_task_results as _utils_submit_task_results,
)

class ValidatorPlatformMixin:
    """Shared IWAP integration helpers extracted from the validator loop."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._validator_auth_message = VALIDATOR_AUTH_MESSAGE or "I am a honest validator"
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

        message = self._validator_auth_message
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
        try:
            self.state_manager.save_checkpoint(tasks=tasks)
        except Exception as exc:
            bt.logging.warning(f"Failed to persist checkpoint: {exc}")

    def _load_round_state(self) -> Optional[Dict[str, Any]]:
        # Wrapper to new checkpoint manager; returns a JSON-like shim for call sites
        ckpt = self.state_manager.load_checkpoint()
        if ckpt is None:
            self._last_resume_info = {"status": "skipped", "reason": "checkpoint not found"}
            return None
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
