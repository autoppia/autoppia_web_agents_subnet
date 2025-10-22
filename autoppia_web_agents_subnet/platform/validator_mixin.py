from __future__ import annotations

import base64
import json
import math
import time
from binascii import Error as BinasciiError
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
import bittensor as bt

from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.config import (
    ROUND_SIZE_EPOCHS,
    IWAP_API_BASE_URL,
    VALIDATOR_NAME,
    VALIDATOR_IMAGE,
    VALIDATOR_AUTH_MESSAGE,
)
from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform import main as iwa_main
from autoppia_web_agents_subnet.platform.state_manager import RoundStateManager
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.domain.classes import Task

IWAP_PHASE_ICON = "🛰️"


class ValidatorPlatformMixin:
    """
    Shared IWAP integration helpers extracted from the validator loop.
    """

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

    def _log_iwap_phase(
        self,
        phase: str,
        message: str,
        *,
        level: str = "info",
        exc_info: bool = False,
    ) -> None:
        """
        Centralized IWAP logging with a consistent icon and message format.
        """
        prefix = f"{IWAP_PHASE_ICON} IWAP {phase}: {message}"
        if level == "success":
            bt.logging.success(prefix)
        elif level == "warning":
            bt.logging.warning(prefix)
        elif level == "error":
            bt.logging.error(prefix, exc_info=exc_info)
        elif level == "debug":
            bt.logging.debug(prefix)
        else:
            bt.logging.info(prefix)

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
            message_bytes = message.encode("utf-8")
            signature_bytes = self.wallet.hotkey.sign(message_bytes)
        except Exception as exc:
            self._log_iwap_phase(
                "Auth",
                f"Failed to sign IWAP auth message: {exc}",
                level="error",
                exc_info=True,
            )
            raise

        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")
        return {
            iwa_main.VALIDATOR_HOTKEY_HEADER: hotkey,
            iwa_main.VALIDATOR_SIGNATURE_HEADER: signature_b64,
        }

    def _build_validator_identity(self) -> iwa_models.ValidatorIdentityIWAP:
        coldkey = getattr(getattr(self.wallet, "coldkeypub", None), "ss58_address", None)
        return iwa_models.ValidatorIdentityIWAP(
            uid=int(self.uid),
            hotkey=self.wallet.hotkey.ss58_address,
            coldkey=coldkey,
        )

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
        collection = getattr(self.metagraph, attribute, None)
        if collection is None:
            bt.logging.debug(f"Metagraph attribute '{attribute}' is unavailable when reading uid={uid}")
            return None
        try:
            value = collection[uid]
            if hasattr(value, "item"):
                return float(value.item())
            return float(value)
        except Exception as exc:
            bt.logging.debug(
                f"Failed to coerce metagraph attribute '{attribute}' for uid={uid}: {exc}",
            )
            return None

    def _normalized_stake_tao(self, uid: int) -> Optional[float]:
        raw_stake = self._metagraph_numeric("S", uid)
        if raw_stake is None:
            bt.logging.warning(f"Stake not available in metagraph for uid={uid}")
            return None

        try:
            rao_per_tao = float(getattr(getattr(bt, "utils", None), "RAO_PER_TAO", 1_000_000_000))
            if not rao_per_tao:
                raise ValueError("Invalid RAO_PER_TAO constant")
        except Exception as exc:
            bt.logging.warning(
                f"Unable to read RAO_PER_TAO constant ({exc}); defaulting to 1e9"
            )
            rao_per_tao = 1_000_000_000

        normalized = raw_stake / rao_per_tao
        bt.logging.debug(
            f"Validator stake normalised for uid={uid}: raw={raw_stake} (RAO) -> {normalized} (TAO)"
        )
        return normalized

    def _validator_vtrust(self, uid: int) -> Optional[float]:
        attribute_order = [
            "validator_trust",
            "validator_performance",
            "v_trust",
            "vtrust",
        ]

        for attribute in attribute_order:
            value = self._metagraph_numeric(attribute, uid)
            if value is not None:
                bt.logging.debug(
                    f"Validator vtrust for uid={uid} resolved via '{attribute}' -> {value}"
                )
                return value

        bt.logging.warning(
            f"Validator vtrust metric not found in metagraph for uid={uid} (checked: {', '.join(attribute_order)})"
        )
        return None

    def _build_validator_snapshot(self, validator_round_id: str) -> iwa_models.ValidatorSnapshotIWAP:
        stake = self._normalized_stake_tao(self.uid)
        vtrust = self._validator_vtrust(self.uid)
        metadata: Dict[str, Any] = {"source": "autoppia_validator"}

        if stake is None:
            bt.logging.warning(
                f"Validator snapshot stake is unavailable for uid={self.uid}; snapshot will omit stake"
            )

        if vtrust is None:
            bt.logging.warning(
                f"Validator snapshot vtrust is unavailable for uid={self.uid}; snapshot will omit vtrust"
            )

        return iwa_models.ValidatorSnapshotIWAP(
            validator_round_id=validator_round_id,
            validator_uid=int(self.uid),
            validator_hotkey=self.wallet.hotkey.ss58_address,
            name=VALIDATOR_NAME,
            stake=stake,
            vtrust=vtrust,
            image_url=VALIDATOR_IMAGE,
            version=self.version,
            metadata=metadata,
        )

    def _build_iwap_tasks(
        self,
        *,
        validator_round_id: str,
        tasks: List[TaskWithProject],
    ) -> Dict[str, iwa_models.TaskIWAP]:
        task_map: Dict[str, iwa_models.TaskIWAP] = {}
        for index, task_item in enumerate(tasks):
            task = task_item.task
            project = task_item.project
            task_id = getattr(task, "id", None) or f"{validator_round_id}_task_{index:04d}"

            specifications = {}
            if hasattr(task, "specifications") and task.specifications is not None:
                try:
                    specifications = task.specifications.model_dump(mode="json", exclude_none=True)  # type: ignore[attr-defined]
                except Exception:
                    specifications = dict(getattr(task, "specifications", {}) or {})

            tests: List[Dict[str, Any]] = []
            for test in getattr(task, "tests", []) or []:
                if hasattr(test, "model_dump"):
                    tests.append(test.model_dump(mode="json", exclude_none=True))
                else:
                    tests.append(dict(test))

            use_case_payload: Dict[str, Any] = {}
            if getattr(task, "use_case", None) is not None:
                use_case = getattr(task, "use_case")
                if hasattr(use_case, "serialize"):
                    try:
                        use_case_payload = use_case.serialize()
                    except Exception:
                        use_case_payload = {}
                elif hasattr(use_case, "model_dump"):
                    use_case_payload = use_case.model_dump(mode="json", exclude_none=True)

            relevant_data = getattr(task, "relevant_data", {}) or {}
            if not isinstance(relevant_data, dict):
                relevant_data = {"value": relevant_data}

            task_model = iwa_models.TaskIWAP(
                task_id=task_id,
                validator_round_id=validator_round_id,
                sequence=index,
                scope="local",
                is_web_real=bool(getattr(task, "is_web_real", False)),
                web_project_id=getattr(project, "id", None),
                url=getattr(task, "url", getattr(project, "frontend_url", "")),
                prompt=getattr(task, "prompt", ""),
                html=getattr(task, "html", "") or "",
                clean_html=getattr(task, "clean_html", "") or "",
                specifications=specifications,
                tests=tests,
                relevant_data=relevant_data,
                use_case=use_case_payload,
                should_record=bool(getattr(task, "should_record", False)),
                interactive_elements=None,
                screenshot=getattr(task, "screenshot", None),
                screenshot_description=getattr(task, "screenshot_description", None),
                milestones=None,
                success_criteria=getattr(task, "success_criteria", None),
            )
            task_map[task_id] = task_model
        return task_map

    async def _iwap_start_round(self, *, current_block: int, n_tasks: int) -> None:
        if not self.current_round_id:
            return

        validator_identity = self._build_validator_identity()
        validator_snapshot = self._build_validator_snapshot(self.current_round_id)
        boundaries = self.round_manager.get_current_boundaries()
        max_epochs = max(1, int(round(ROUND_SIZE_EPOCHS))) if ROUND_SIZE_EPOCHS else 1
        start_epoch_raw = boundaries["round_start_epoch"]
        start_epoch = math.floor(start_epoch_raw)
        round_metadata: Dict[str, Any] = {
            "round_start_epoch_raw": start_epoch_raw,
            "target_epoch": boundaries.get("target_epoch"),
        }

        round_number = await self.round_manager.calculate_round(current_block)
        miner_count = len(getattr(self, "active_miner_uids", []))

        start_round_message = (
            f"Calling start_round with round_number={round_number}, "
            f"tasks={n_tasks}, miners={miner_count}, "
            f"round_id={self.current_round_id}"
        )
        self._log_iwap_phase("Phase 1", start_round_message)

        try:
            await self.iwap_client.auth_check()
        except Exception as exc:
            self._log_iwap_phase(
                "Auth",
                f"Validator auth check failed – aborting round: {exc}",
                level="error",
                exc_info=True,
            )
            raise SystemExit("Validator authentication failed; shutting down") from exc

        validator_round = iwa_models.ValidatorRoundIWAP(
            validator_round_id=self.current_round_id,
            round_number=round_number,
            validator_uid=int(self.uid),
            validator_hotkey=validator_identity.hotkey,
            validator_coldkey=validator_identity.coldkey,
            start_block=current_block,
            start_epoch=start_epoch,
            max_epochs=max_epochs,
            max_blocks=self.round_manager.BLOCKS_PER_EPOCH,
            n_tasks=n_tasks,
            n_miners=len(self.active_miner_uids),
            n_winners=max(1, len(self.active_miner_uids)) if self.active_miner_uids else 1,
            started_at=self.round_start_timestamp or time.time(),
            summary={"tasks": n_tasks},
            metadata=round_metadata,
        )

        if self._phases.get("p1_done"):
            self._log_iwap_phase("Phase 1", "resume: skipping start_round (already done)", level="warning")
        else:
            try:
                await self.iwap_client.start_round(
                    validator_identity=validator_identity,
                    validator_round=validator_round,
                    validator_snapshot=validator_snapshot,
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (409, 500):
                    self._log_iwap_phase(
                        "Phase 1",
                        f"start_round returned {status} (already exists); continuing idempotently",
                        level="warning",
                    )
                    self._phases["p1_done"] = True
                else:
                    self._log_iwap_phase(
                        "Phase 1",
                        f"start_round failed for round_id={self.current_round_id}",
                        level="error",
                        exc_info=True,
                    )
                    return
            except Exception:
                self._log_iwap_phase(
                    "Phase 1",
                    f"start_round failed for round_id={self.current_round_id}",
                    level="error",
                    exc_info=True,
                )
                return
            else:
                self._log_iwap_phase(
                    "Phase 1",
                    f"start_round completed for round_id={self.current_round_id}",
                    level="success",
                )
                self._phases["p1_done"] = True
            finally:
                try:
                    self._save_round_state()
                except Exception:
                    pass

        task_count = len(self.current_round_tasks)
        set_tasks_message = (
            f"Calling set_tasks with tasks={task_count} "
            f"for round_id={self.current_round_id}"
        )
        if self._phases.get("p2_done"):
            self._log_iwap_phase("Phase 2", "resume: skipping set_tasks (already done)", level="warning")
        else:
            self._log_iwap_phase("Phase 2", set_tasks_message)

            try:
                await self.iwap_client.set_tasks(
                    validator_round_id=self.current_round_id,
                    tasks=self.current_round_tasks.values(),
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (409, 500):
                    self._log_iwap_phase(
                        "Phase 2",
                        f"set_tasks returned {status} (duplicates); continuing idempotently",
                        level="warning",
                    )
                    self._phases["p2_done"] = True
                else:
                    self._log_iwap_phase(
                        "Phase 2",
                        f"set_tasks failed for round_id={self.current_round_id}",
                        level="error",
                        exc_info=True,
                    )
                    return
            except Exception:
                self._log_iwap_phase(
                    "Phase 2",
                    f"set_tasks failed for round_id={self.current_round_id}",
                    level="error",
                    exc_info=True,
                )
                return
            else:
                self._log_iwap_phase(
                    "Phase 2",
                    f"set_tasks completed for round_id={self.current_round_id}",
                    level="success",
                )
                self._phases["p2_done"] = True
            finally:
                try:
                    self._save_round_state()
                except Exception:
                    pass

        coldkeys = getattr(self.metagraph, "coldkeys", [])
        now_ts = time.time()
        for miner_uid in self.active_miner_uids:
            miner_hotkey = None
            try:
                miner_hotkey = self.metagraph.hotkeys[miner_uid]
            except Exception:
                pass

            miner_coldkey = None
            try:
                if coldkeys:
                    miner_coldkey = coldkeys[miner_uid]
            except Exception:
                miner_coldkey = None

            handshake_payload = self.round_handshake_payloads.get(miner_uid)

            miner_identity = iwa_main.build_miner_identity(
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                miner_coldkey=miner_coldkey,
                agent_key=None,
            )
            miner_snapshot = iwa_main.build_miner_snapshot(
                validator_round_id=self.current_round_id,
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                miner_coldkey=miner_coldkey,
                agent_key=None,
                handshake_payload=handshake_payload,
                now_ts=now_ts,
            )

            # Reuse saved agent_run_id if available
            existing_run = self.current_agent_runs.get(miner_uid)
            agent_run_id = existing_run.agent_run_id if existing_run else iwa_main.generate_agent_run_id(miner_uid)
            agent_run = iwa_models.AgentRunIWAP(
                agent_run_id=agent_run_id,
                validator_round_id=self.current_round_id,
                validator_uid=int(self.uid),
                validator_hotkey=validator_identity.hotkey,
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                miner_agent_key=None,
                is_sota=False,
                version=getattr(handshake_payload, "agent_version", None),
                started_at=now_ts,
                metadata={"handshake_note": getattr(handshake_payload, "note", None)},
            )

            try:
                if existing_run:
                    # Already started; ensure snapshots/accumulators present
                    self._log_iwap_phase(
                        "Phase 3",
                        f"resume: skipping start_agent_run for miner_uid={miner_uid} (already started)",
                        level="warning",
                    )
                    self.current_agent_runs[miner_uid] = existing_run
                    self.current_miner_snapshots[miner_uid] = self.current_miner_snapshots.get(miner_uid) or miner_snapshot
                    self.agent_run_accumulators.setdefault(
                        miner_uid,
                        {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0},
                    )
                    # Persist and continue
                    try:
                        self._save_round_state()
                    except Exception:
                        pass
                    continue
                start_agent_run_message = (
                    f"Calling start_agent_run for miner_uid={miner_uid}, "
                    f"agent_run_id={agent_run_id}"
                )
                self._log_iwap_phase("Phase 3", start_agent_run_message)
                await self.iwap_client.start_agent_run(
                    validator_round_id=self.current_round_id,
                    agent_run=agent_run,
                    miner_identity=miner_identity,
                    miner_snapshot=miner_snapshot,
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (409, 500):
                    self._log_iwap_phase(
                        "Phase 3",
                        f"start_agent_run returned {status} for miner_uid={miner_uid} (already exists); continuing",
                        level="warning",
                    )
                else:
                    start_agent_run_error = (
                        f"start_agent_run failed for miner_uid={miner_uid}, "
                        f"agent_run_id={agent_run_id}"
                    )
                    self._log_iwap_phase(
                        "Phase 3",
                        start_agent_run_error,
                        level="error",
                        exc_info=True,
                    )
                    continue
            except Exception:
                start_agent_run_error = (
                    f"start_agent_run failed for miner_uid={miner_uid}, "
                    f"agent_run_id={agent_run_id}"
                )
                self._log_iwap_phase(
                    "Phase 3",
                    start_agent_run_error,
                    level="error",
                    exc_info=True,
                )
                continue
            else:
                start_agent_run_success = (
                    f"start_agent_run completed for miner_uid={miner_uid}, "
                    f"agent_run_id={agent_run_id}"
                )
                self._log_iwap_phase(
                    "Phase 3",
                    start_agent_run_success,
                    level="success",
                )
                self.current_agent_runs[miner_uid] = agent_run
                self.current_miner_snapshots[miner_uid] = miner_snapshot
                self.agent_run_accumulators[miner_uid] = {
                    "reward": 0.0,
                    "score": 0.0,
                    "execution_time": 0.0,
                    "tasks": 0,
                }
                # Persist state progressively
                try:
                    self._save_round_state()
                except Exception:
                    pass

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
        if not self.current_round_id or not self.current_round_tasks:
            return

        task = task_item.task
        task_id = getattr(task, "id", None)
        if task_id is None:
            return

        task_payload = self.current_round_tasks.get(task_id)
        if task_payload is None:
            return

        # For demo (non-real) web projects, override the task.url that is
        # sent with add_evaluation so the dashboard shows the demo project
        # name instead of a localhost host:port. Real websites keep their URL.
        try:
            if not getattr(task_payload, "is_web_real", False):
                project_name = getattr(task_item.project, "name", None)
                if project_name:
                    task_payload.url = str(project_name)
        except Exception:
            # Do not block the round on display-only override failures
            pass

        validator_hotkey = self.wallet.hotkey.ss58_address

        for idx, miner_uid in enumerate(self.active_miner_uids):
            if idx >= len(task_solutions):
                break

            agent_run = self.current_agent_runs.get(miner_uid)
            if agent_run is None:
                continue

            miner_hotkey = None
            try:
                miner_hotkey = self.metagraph.hotkeys[miner_uid]
            except Exception:
                miner_hotkey = None

            solution = task_solutions[idx]
            actions_payload: List[Dict[str, Any]] = []

            # 🔍 DEBUG: Log actions conversion
            raw_actions = getattr(solution, "actions", []) or []
            self._log_iwap_phase("Phase 4", f"🔧 Converting {len(raw_actions)} actions for miner_uid={miner_uid}", level="debug")

            for action_idx, action in enumerate(raw_actions):
                if hasattr(action, "model_dump"):
                    action_dict = action.model_dump(mode="json", exclude_none=True)
                    actions_payload.append(action_dict)
                    self._log_iwap_phase("Phase 4", f"  Action {action_idx} (model_dump): {action_dict}", level="debug")
                elif hasattr(action, "__dict__"):
                    action_dict = dict(action.__dict__)
                    actions_payload.append(action_dict)
                    self._log_iwap_phase("Phase 4", f"  Action {action_idx} (__dict__): {action_dict}", level="debug")
                else:
                    action_dict = {"type": getattr(action, "type", "unknown")}
                    actions_payload.append(action_dict)
                    self._log_iwap_phase("Phase 4", f"  Action {action_idx} (fallback): {action_dict}", level="debug")

            task_solution_id = iwa_main.generate_task_solution_id(task_id, miner_uid)
            evaluation_id = iwa_main.generate_evaluation_id(task_id, miner_uid)
            final_score = float(eval_scores[idx]) if idx < len(eval_scores) else 0.0
            evaluation_meta = evaluation_results[idx] if idx < len(evaluation_results) else {}
            if not isinstance(evaluation_meta, dict):
                evaluation_meta = {}
            evaluation_metadata = dict(evaluation_meta)
            gif_payload = evaluation_metadata.pop("gif_recording", evaluation_meta.get("gif_recording"))
            test_results_data = test_results_list[idx] if idx < len(test_results_list) else []
            exec_time = float(execution_times[idx]) if idx < len(execution_times) else 0.0
            reward_value = rewards[idx] if idx < len(rewards) else final_score

            task_solution_payload = iwa_models.TaskSolutionIWAP(
                solution_id=task_solution_id,
                task_id=task_id,
                agent_run_id=agent_run.agent_run_id,
                validator_round_id=self.current_round_id,
                validator_uid=int(self.uid),
                validator_hotkey=validator_hotkey,
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                miner_agent_key=None,
                actions=actions_payload,
                web_agent_id=getattr(solution, "web_agent_id", None),
                recording=getattr(solution, "recording", None),
            )

            evaluation_result_payload = iwa_models.EvaluationResultIWAP(
                evaluation_id=evaluation_id,
                validator_round_id=self.current_round_id,
                agent_run_id=agent_run.agent_run_id,
                task_id=task_id,
                task_solution_id=task_solution_id,
                validator_uid=int(self.uid),
                miner_uid=miner_uid,
                final_score=final_score,
                test_results=test_results_data or [],
                execution_history=evaluation_meta.get("execution_history", []),
                feedback=evaluation_meta.get("feedback"),
                web_agent_id=getattr(solution, "web_agent_id", None),
                raw_score=evaluation_meta.get("raw_score", final_score),
                evaluation_time=evaluation_meta.get("evaluation_time", exec_time),
                stats=evaluation_meta.get("stats"),
                gif_recording=None,  # Will be updated with URL after upload
                metadata=evaluation_metadata,
            )

            # Skip if already completed (resume mode)
            if (miner_uid, task_id) in self._completed_pairs:
                self._log_iwap_phase(
                    "Phase 4",
                    f"⏭️ Skipping add_evaluation for miner_uid={miner_uid}, task_id={task_id} (already completed)",
                    level="warning",
                )
                continue

            add_evaluation_message = (
                f"Calling add_evaluation for miner_uid={miner_uid}, "
                f"task_id={task_id}, agent_run_id={agent_run.agent_run_id}"
            )
            self._log_iwap_phase("Phase 4", add_evaluation_message)

            # Store GIF for later upload (after evaluation is created)
            gif_to_upload = None
            if gif_payload:
                payload_size = len(gif_payload) if isinstance(gif_payload, (bytes, str)) else 0
                self._log_iwap_phase(
                    "Phase 4",
                    f"🎬 GIF detected: {payload_size} bytes - will upload after creating evaluation",
                    level="debug",
                )
                gif_to_upload = gif_payload
                # Don't include GIF in evaluation payload - will upload separately
                evaluation_result_payload.gif_recording = None
            else:
                self._log_iwap_phase(
                    "Phase 4",
                    f"No GIF payload received for evaluation_id={evaluation_id}",
                    level="debug",
                )

            # Detailed payload will be logged in main.py add_evaluation method

            try:
                await self.iwap_client.add_evaluation(
                    validator_round_id=self.current_round_id,
                    agent_run_id=agent_run.agent_run_id,
                    task=task_payload,
                    task_solution=task_solution_payload,
                    evaluation_result=evaluation_result_payload,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 409:
                    # Treat as idempotent – mark completed
                    self._log_iwap_phase(
                        "Phase 4",
                        f"add_evaluation returned 409 for miner_uid={miner_uid}, task_id={task_id}; marking as completed",
                        level="warning",
                    )
                    self._completed_pairs.add((miner_uid, task_id))
                    try:
                        self._save_round_state()
                    except Exception:
                        pass
                    continue
                else:
                    add_evaluation_error = (
                        f"add_evaluation failed for miner_uid={miner_uid}, "
                        f"task_id={task_id}"
                    )
                    self._log_iwap_phase(
                        "Phase 4",
                        add_evaluation_error,
                        level="error",
                        exc_info=True,
                    )
                    continue
            except Exception:
                add_evaluation_error = (
                    f"add_evaluation failed for miner_uid={miner_uid}, "
                    f"task_id={task_id}"
                )
                self._log_iwap_phase(
                    "Phase 4",
                    add_evaluation_error,
                    level="error",
                    exc_info=True,
                )
            else:
                add_evaluation_success = (
                    f"add_evaluation completed for miner_uid={miner_uid}, "
                    f"task_id={task_id}"
                )
                self._log_iwap_phase(
                    "Phase 4",
                    add_evaluation_success,
                    level="success",
                )
                # Cache evaluation record for resume rebuild
                try:
                    self._eval_records.append(
                        {
                            "miner_uid": miner_uid,
                            "task_id": task_id,
                            "reward": float(reward_value),
                            "final_score": float(final_score),
                            "exec_time": float(exec_time),
                        }
                    )
                except Exception:
                    pass
                # Record completion and persist
                self._completed_pairs.add((miner_uid, task_id))
                try:
                    self._save_round_state()
                except Exception:
                    pass

                # 🎬 Now upload GIF to AWS (evaluation exists now)
                if gif_to_upload:
                    gif_bytes = self._extract_gif_bytes(gif_to_upload)
                    if gif_bytes:
                        self._log_iwap_phase(
                            "Phase 4",
                            f"🎬 Uploading GIF to AWS for evaluation_id={evaluation_id} bytes={len(gif_bytes)}",
                        )
                        try:
                            uploaded_url = await self.iwap_client.upload_evaluation_gif(evaluation_id, gif_bytes)
                            if uploaded_url:
                                self._log_iwap_phase(
                                    "Phase 4",
                                    f"✅ GIF uploaded successfully to AWS: {uploaded_url}",
                                    level="success",
                                )
                            else:
                                self._log_iwap_phase(
                                    "Phase 4",
                                    f"⚠️  GIF upload completed without URL for evaluation_id={evaluation_id}",
                                    level="warning",
                                )
                        except Exception as e:
                            self._log_iwap_phase(
                                "Phase 4",
                                f"❌ Failed to upload GIF for evaluation_id={evaluation_id}: {str(e)}",
                                level="error",
                                exc_info=True,
                            )
                    else:
                        self._log_iwap_phase(
                            "Phase 4",
                            f"⚠️  Skipped GIF upload: invalid payload (failed to extract bytes) for evaluation_id={evaluation_id}",
                            level="warning",
                        )

            accumulators = self.agent_run_accumulators.setdefault(
                miner_uid,
                {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0},
            )
            accumulators["reward"] += float(reward_value)
            accumulators["score"] += float(final_score)
            accumulators["execution_time"] += exec_time
            accumulators["tasks"] += 1

            agent_run.total_tasks = accumulators["tasks"]
            agent_run.completed_tasks = accumulators["tasks"]
            agent_run.total_reward = accumulators["reward"]
            agent_run.average_reward = accumulators["reward"] / accumulators["tasks"]
            agent_run.average_score = accumulators["score"] / accumulators["tasks"]
            agent_run.average_execution_time = accumulators["execution_time"] / accumulators["tasks"]

    @staticmethod
    def _extract_gif_bytes(payload: Optional[object]) -> Optional[bytes]:
        if payload is None:
            bt.logging.debug("🛰️ IWAP GIF extraction skipped: payload is None")
            return None

        if isinstance(payload, (bytes, bytearray)):
            candidate = bytes(payload)
            if candidate.startswith((b"GIF87a", b"GIF89a")):
                bt.logging.debug("🛰️ IWAP GIF extraction succeeded for binary payload (bytes=%s)", len(candidate))
                return candidate
            raw_source = candidate
        elif isinstance(payload, str):
            text = payload.strip()
            if not text:
                bt.logging.warning("🛰️ IWAP GIF extraction failed: string payload is empty after strip")
                return None
            raw_source = text.encode("utf-8")
        else:
            bt.logging.warning(
                "🛰️ IWAP GIF extraction failed: unsupported payload type %s",
                type(payload).__name__,
            )
            return None

        try:
            decoded = base64.b64decode(raw_source, validate=True)
        except (BinasciiError, ValueError) as exc:
            bt.logging.warning("🛰️ IWAP GIF extraction failed: base64 decode error %s", exc)
            return None

        if decoded.startswith((b"GIF87a", b"GIF89a")):
            bt.logging.debug("🛰️ IWAP GIF extraction decoded GIF successfully (bytes=%s)", len(decoded))
            return decoded
        bt.logging.warning("🛰️ IWAP GIF extraction failed: decoded payload missing GIF header")
        return None

    async def _finish_iwap_round(
        self,
        *,
        avg_rewards: Dict[int, float],
        final_weights: Dict[int, float],
        tasks_completed: int,
    ) -> None:
        if not self.current_round_id:
            return

        ended_at = time.time()
        for agent_run in self.current_agent_runs.values():
            agent_run.ended_at = ended_at
            agent_run.elapsed_sec = max(0.0, ended_at - agent_run.started_at)

        sorted_miners = sorted(avg_rewards.items(), key=lambda item: item[1], reverse=True)
        winners: List[iwa_models.RoundWinnerIWAP] = []
        winner_scores: List[float] = []
        for rank, (uid, score) in enumerate(sorted_miners[:3], start=1):
            miner_hotkey = None
            try:
                miner_hotkey = self.metagraph.hotkeys[uid]
            except Exception:
                miner_hotkey = None
            winners.append(
                iwa_models.RoundWinnerIWAP(
                    miner_uid=uid,
                    miner_hotkey=miner_hotkey,
                    rank=rank,
                    score=float(score),
                )
            )
            winner_scores.append(float(score))

        weights_payload = {str(uid): float(weight) for uid, weight in final_weights.items()}
        summary = {
            "tasks_completed": tasks_completed,
            "active_miners": len(avg_rewards),
        }

        rank_map = {uid: rank for rank, (uid, _score) in enumerate(sorted_miners, start=1)}
        agent_run_summaries: List[iwa_models.FinishRoundAgentRunIWAP] = []
        for miner_uid, agent_run in self.current_agent_runs.items():
            rank_value = rank_map.get(miner_uid)
            weight_value = final_weights.get(miner_uid)
            agent_run_summaries.append(
                iwa_models.FinishRoundAgentRunIWAP(
                    agent_run_id=agent_run.agent_run_id,
                    rank=rank_value,
                    weight=float(weight_value) if weight_value is not None else None,
                )
            )

        finish_request = iwa_models.FinishRoundIWAP(
            status="completed",
            winners=winners,
            winner_scores=winner_scores,
            weights=weights_payload,
            ended_at=ended_at,
            summary=summary,
            agent_runs=agent_run_summaries,
        )

        round_id = self.current_round_id
        finish_round_message = (
            f"Calling finish_round for round_id={round_id}, "
            f"winners={len(winners)}, tasks_completed={tasks_completed}"
        )
        self._log_iwap_phase("Phase 5", finish_round_message)
        try:
            await self.iwap_client.finish_round(
                validator_round_id=round_id,
                finish_request=finish_request,
            )
        except Exception:
            self._log_iwap_phase(
                "Phase 5",
                f"finish_round failed for round_id={round_id}",
                level="error",
                exc_info=True,
            )
            raise
        else:
            self._log_iwap_phase(
                "Phase 5",
                f"finish_round completed for round_id={round_id}",
                level="success",
            )
        finally:
            self._reset_iwap_round_state()
            self._remove_round_state()

    def _reset_iwap_round_state(self) -> None:
        self.current_round_id = None
        self.current_round_tasks = {}
        self.current_agent_runs = {}
        self.current_miner_snapshots = {}
        self.round_handshake_payloads = {}
        self.round_start_timestamp = 0.0
        self.agent_run_accumulators = {}
        self._completed_pairs = set()
