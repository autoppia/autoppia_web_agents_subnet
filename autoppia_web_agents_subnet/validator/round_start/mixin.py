from __future__ import annotations

import asyncio
import json
import socket
import time
from collections import Counter
from pathlib import Path
import bittensor as bt

from autoppia_web_agents_subnet.opensource.utils_docker import get_client
from autoppia_web_agents_subnet.utils.log_colors import round_details_tag
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

from autoppia_web_agents_subnet.protocol import StartRoundSynapse
from autoppia_web_agents_subnet.validator.models import AgentInfo
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.round_start.types import RoundStartResult
from autoppia_web_agents_subnet.opensource.utils_git import (
    normalize_and_validate_github_url,
    resolve_remote_ref_commit,
)
from autoppia_web_agents_subnet.validator.config import (
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION,
    MIN_MINER_STAKE_ALPHA,
    MAX_MINERS_PER_ROUND_BY_STAKE,
    MAX_MINERS_PER_COLDKEY,
    MAX_MINERS_PER_REPO,
    EVALUATION_COOLDOWN_MIN_ROUNDS,
    EVALUATION_COOLDOWN_MAX_ROUNDS,
    EVALUATION_COOLDOWN_NO_RESPONSE_BADNESS,
    EVALUATION_COOLDOWN_ZERO_SCORE_BADNESS,
    SANDBOX_GATEWAY_PORT,
)
from autoppia_web_agents_subnet.validator.round_start.synapse_handler import send_start_round_synapse_to_miners


def _commits_match(a: str | None, b: str | None) -> bool:
    """
    Treat short git hashes as equal to their full-length prefix.

    This helps skip re-evaluation when miners submit GitHub /commit/<sha> URLs
    that may use a shortened SHA.
    """
    if not a or not b:
        return False
    a_s = str(a).strip()
    b_s = str(b).strip()
    if not a_s or not b_s:
        return False
    if a_s == b_s:
        return True
    if len(a_s) >= 7 and len(b_s) >= 7 and (a_s.startswith(b_s) or b_s.startswith(a_s)):
        return True
    return False


def _clear_queue_best_effort(q: object) -> None:
    """
    Clear a queue.Queue without assuming it's always a real queue in unit tests.
    """
    try:
        inner = getattr(q, "queue", None)
        if inner is not None and hasattr(inner, "clear"):
            inner.clear()
            return
    except Exception:
        pass

    # Fallback: drain via get_nowait() if available.
    try:
        empty = getattr(q, "empty", None)
        get_nowait = getattr(q, "get_nowait", None)
        if callable(empty) and callable(get_nowait):
            while not empty():
                get_nowait()
    except Exception:
        pass


def _resolve_adaptive_cooldown_rounds(
    *,
    miner_score: float | None,
    best_score_ever: float | None,
    handshake_responded: bool,
) -> int:
    min_rounds = max(0, int(EVALUATION_COOLDOWN_MIN_ROUNDS))
    max_rounds = max(min_rounds, int(EVALUATION_COOLDOWN_MAX_ROUNDS))
    if min_rounds == max_rounds:
        return min_rounds

    best_score = float(best_score_ever) if isinstance(best_score_ever, (int, float)) else 1.0
    if best_score <= 0.0:
        best_score = 1.0

    score = float(miner_score or 0.0)
    score = max(0.0, min(score, best_score))
    quality_ratio = score / best_score

    # Higher value => worse miner => longer cooldown.
    badness = 1.0 - quality_ratio
    if score <= 0.0:
        badness += float(EVALUATION_COOLDOWN_ZERO_SCORE_BADNESS)
    if not handshake_responded:
        badness += float(EVALUATION_COOLDOWN_NO_RESPONSE_BADNESS)

    badness = max(0.0, min(1.0, badness))
    cooldown = min_rounds + int(round(badness * (max_rounds - min_rounds)))
    return max(min_rounds, min(max_rounds, cooldown))


def _is_cooldown_active(
    *,
    current_round: int,
    last_evaluated_round: int | None,
    miner_score: float | None,
    best_score_ever: float | None = None,
    handshake_responded: bool = True,
) -> bool:
    if not isinstance(last_evaluated_round, int):
        return False
    effective_cooldown = _resolve_adaptive_cooldown_rounds(
        miner_score=miner_score,
        best_score_ever=best_score_ever,
        handshake_responded=handshake_responded,
    )
    return (current_round - last_evaluated_round) < effective_cooldown


class ValidatorRoundStartMixin:
    """Round preparation: pre-generate tasks, and perform handshake."""

    @staticmethod
    def _is_local_tcp_port_open(port: int, timeout_seconds: float = 0.75) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=float(timeout_seconds)):
                return True
        except Exception:
            return False

    def _log_round_start_runtime_healthcheck(self) -> None:
        """
        Print a compact runtime health snapshot at round start:
        - Docker daemon availability
        - Relevant container status/health/ports
        - Local TCP checks for critical ports (demo backend and sandbox gateway)
        """
        bt.logging.info(round_details_tag("🔎 Runtime Healthcheck"))

        try:
            docker_client = get_client()
            docker_ok = bool(docker_client.ping())
            bt.logging.info(round_details_tag(f"Docker daemon: {'OK' if docker_ok else 'UNHEALTHY'}"))

            containers = docker_client.containers.list(all=True)
            relevant_rows: list[tuple[str, str, str, str, str]] = []

            for container in containers:
                try:
                    container.reload()
                    attrs = container.attrs or {}
                except Exception:
                    attrs = {}

                name = str(getattr(container, "name", "unknown") or "unknown")
                state = str((attrs.get("State") or {}).get("Status") or getattr(container, "status", "unknown"))
                health = str(((attrs.get("State") or {}).get("Health") or {}).get("Status") or "-")
                image = str((attrs.get("Config") or {}).get("Image") or "?")
                ports_map = (attrs.get("NetworkSettings") or {}).get("Ports") or {}

                host_ports: set[int] = set()
                compact_ports: list[str] = []
                try:
                    for container_port, host_bindings in ports_map.items():
                        if not host_bindings:
                            continue
                        for binding in host_bindings:
                            host_port_raw = binding.get("HostPort")
                            if not host_port_raw:
                                continue
                            try:
                                host_port = int(host_port_raw)
                            except Exception:
                                continue
                            host_ports.add(host_port)
                            compact_ports.append(f"{container_port}->{host_port}")
                except Exception:
                    pass

                name_l = name.lower()
                relevant = name_l.startswith("sandbox-") or "demo" in name_l or "iwap" in name_l or "autoppia" in name_l or 8090 in host_ports or int(SANDBOX_GATEWAY_PORT) in host_ports
                if not relevant:
                    continue

                ports_str = ",".join(sorted(set(compact_ports))) if compact_ports else "-"
                relevant_rows.append((name, state, health, ports_str, image))

            if not relevant_rows:
                bt.logging.warning(round_details_tag("Docker containers (relevant): none found (sandbox/demo/iwap/8090/gateway)"))
            else:
                bt.logging.info(round_details_tag(f"Docker containers (relevant): {len(relevant_rows)}"))
                for name, state, health, ports_str, image in sorted(relevant_rows, key=lambda row: row[0]):
                    bt.logging.info(round_details_tag(f"[docker] {name} | state={state} | health={health} | ports={ports_str} | image={image}"))
        except Exception as exc:
            bt.logging.warning(round_details_tag(f"Docker healthcheck error: {exc}"))

        critical_ports = [8090, int(SANDBOX_GATEWAY_PORT)]
        for port in critical_ports:
            is_open = self._is_local_tcp_port_open(port)
            bt.logging.info(round_details_tag(f"[tcp] 127.0.0.1:{port} => {'OPEN' if is_open else 'CLOSED'}"))

    async def _start_round(self) -> RoundStartResult:
        current_block = self.block

        # Configure season start block in RoundManager (from SeasonManager)
        season_start_block = self.season_manager.get_season_start_block(current_block)
        self.round_manager.set_season_start_block(season_start_block)
        self.round_manager.sync_boundaries(current_block)
        current_fraction = float(self.round_manager.fraction_elapsed(current_block))

        if current_fraction > SKIP_ROUND_IF_STARTED_AFTER_FRACTION:
            # Too late to start a clean round; wait for the next boundary if a
            # waiter helper is available (tests patch this).
            try:
                waiter = getattr(self, "_wait_until_specific_block", None)
                if callable(waiter) and self.round_manager.target_block is not None:
                    await waiter(
                        target_block=int(self.round_manager.target_block),
                        target_description="next round boundary",
                    )
            except Exception:
                pass
            return RoundStartResult(
                continue_forward=False,
                reason="late in round",
            )

        if self.season_manager.should_start_new_season(current_block):
            await self.season_manager.generate_season_tasks(current_block, self.round_manager)
            while not self.agents_queue.empty():
                self.agents_queue.get()
            self.agents_dict = {}
            self.agents_on_first_handshake = []
            self.should_update_weights = False
            # Reset per-season repo-owner gating to allow fresh distribution each season.
            self._season_repo_owners = {}
            # New season = new tasks → re-evaluate all commits; clear "already evaluated" map.
            if hasattr(self, "_evaluated_commits_by_miner"):
                self._evaluated_commits_by_miner = {}
                try:
                    self._save_iwap_prev_round_state()
                except Exception:
                    pass

        current_block = self.block
        self.round_manager.start_new_round(current_block)

        # Always generate a fresh IWAP round id for the new round. Some settlement
        # code paths (e.g. burn/no-op) may skip IWAP finish/reset, so relying on
        # "only if not set" can cause stale IDs to leak into subsequent rounds.
        self.current_round_id = self._generate_validator_round_id(current_block=current_block)

        # Set round start timestamp
        self.round_start_timestamp = time.time()

        # Configure per-round log file (data/logs/season-<season>-round-<round>.log).
        round_id_for_log = self.current_round_id
        try:
            ColoredLogger.set_round_log_file(str(round_id_for_log))
        except Exception:
            pass

        wait_info = self.round_manager.get_wait_info(current_block)

        # Calculate settlement block and ETA
        settlement_block = self.round_manager.settlement_block
        settlement_epoch = self.round_manager.settlement_epoch
        blocks_to_settlement = max(settlement_block - current_block, 0) if settlement_block else 0
        minutes_to_settlement = (blocks_to_settlement * self.round_manager.SECONDS_PER_BLOCK) / 60.0

        bt.logging.info("=" * 100)
        bt.logging.info(round_details_tag("🚀 ROUND START"))
        bt.logging.info(round_details_tag(f"Season Number: {self.season_manager.season_number}"))
        bt.logging.info(round_details_tag(f"Round Number: {self.round_manager.round_number}"))
        bt.logging.info(round_details_tag(f"Round Start Epoch: {self.round_manager.start_epoch:.2f}"))
        bt.logging.info(round_details_tag(f"Round Target Epoch: {self.round_manager.target_epoch:.2f}"))
        bt.logging.info(round_details_tag(f"Validator Round ID: {self.current_round_id}"))
        bt.logging.info(round_details_tag(f"Current Block: {current_block:,}"))
        bt.logging.info(round_details_tag(f"Duration: ~{wait_info['minutes_to_target']:.1f} minutes"))
        bt.logging.info(round_details_tag(f"Total Blocks: {self.round_manager.target_block - current_block}"))
        bt.logging.info(round_details_tag(f"Consensus fetch: {self.round_manager.settlement_fraction:.0%} — block {settlement_block:,} (epoch {settlement_epoch:.2f}) — ~{minutes_to_settlement:.1f}m"))
        bt.logging.info("=" * 100)
        self._log_round_start_runtime_healthcheck()

        # Save round boundaries for settlement so we wait for *this* round's 97% and end,
        # not the next round's (sync_boundaries(current_block) later would advance to next round).
        self._settlement_round_start_block = self.round_manager.start_block
        self._settlement_round_target_block = self.round_manager.target_block
        self._settlement_round_fetch_block = settlement_block

        return RoundStartResult(
            continue_forward=True,
            reason="Round Started Successfully",
        )

    async def _perform_handshake(self) -> None:
        """
        Perform StartRound handshake and collect new submitted agents
        """
        # Each round we rebuild the evaluation queue from scratch (based on the
        # current stake window + cooldown) to keep evaluation cost/time bounded.
        try:
            _clear_queue_best_effort(getattr(self, "agents_queue", None))
        except Exception:
            pass

        # Guard: metagraph must be available.
        metagraph = getattr(self, "metagraph", None)
        if metagraph is None:
            bt.logging.warning("No metagraph on validator; skipping handshake")
            return

        n = int(getattr(metagraph, "n", 0) or 0)
        if n <= 0:
            bt.logging.warning("Metagraph has no peers; skipping handshake")
            return

        # Resolve stakes if present; otherwise treat as zero.
        try:
            stakes = list(getattr(metagraph, "stake", [0.0] * n))
        except Exception:
            stakes = [0.0] * n
        coldkeys = list(getattr(metagraph, "coldkeys", []))
        max_by_coldkey = int(MAX_MINERS_PER_COLDKEY)
        max_by_repo = int(MAX_MINERS_PER_REPO)

        validator_uid = int(getattr(self, "uid", 0) or 0)
        min_stake = float(MIN_MINER_STAKE_ALPHA)

        # Filter candidate miner UIDs by minimum stake and excluding validator itself.
        candidate_uids: list[int] = []
        candidate_stakes: list[tuple[float, int, str]] = []
        skipped_below_stake = 0
        coldkey_cap_skip_count = 0
        skipped_stake_cap = 0

        for uid in range(n):
            if uid == validator_uid:
                continue
            stake_val = float(stakes[uid]) if uid < len(stakes) else 0.0
            if stake_val >= min_stake:
                coldkey = ""
                if 0 <= uid < len(coldkeys):
                    raw_coldkey = coldkeys[uid]
                    if raw_coldkey:
                        coldkey = str(raw_coldkey).strip()
                candidate_stakes.append((stake_val, uid, coldkey))
            else:
                skipped_below_stake += 1
                bt.logging.debug(f"[handshake] Skipping uid={uid} stake={stake_val:.4f} < MIN_MINER_STAKE_ALPHA={min_stake:.4f}")

        if not candidate_stakes:
            bt.logging.warning(f"No miners meet MIN_MINER_STAKE_ALPHA={min_stake:.4f}; active_miner_uids will be empty")
            return

        candidates_after_stake = len(candidate_stakes)

        # Sort by stake before capping per coldkey and per round.
        candidate_stakes.sort(key=lambda item: float(item[0]), reverse=True)

        # Coldkey cap is enforced after handshakes on valid submissions (after missing-fields validation).
        coldkey_counts: dict[str, int] = {}
        candidate_uids = [uid for _, uid, _ in candidate_stakes]

        # Rebuild stake-sorted list after coldkey capping.
        candidate_stakes = [(float(stakes[uid]) if uid < len(stakes) else 0.0, uid) for uid in candidate_uids]
        candidate_stakes.sort(key=lambda item: item[0], reverse=True)

        # Optional: restrict to the top N miners by stake to bound evaluation work.
        max_by_stake = int(MAX_MINERS_PER_ROUND_BY_STAKE)
        if max_by_stake > 0 and len(candidate_stakes) > max_by_stake:
            skipped_stake_cap = max(0, len(candidate_stakes) - max_by_stake)
            try:
                candidate_uids = [uid for _, uid in candidate_stakes[:max_by_stake]]
            except Exception:
                candidate_uids = candidate_uids[:max_by_stake]
        else:
            candidate_uids = [uid for _, uid in candidate_stakes]

        bt.logging.info(
            "[handshake] Candidate selection summary "
            f"total={n - 1}|eligible_by_stake={candidates_after_stake}|"
            f"below_stake={skipped_below_stake}|"
            f"coldkey_cap_skip={coldkey_cap_skip_count}|stake_cap_skip={skipped_stake_cap}|"
            f"final_candidates={len(candidate_uids)}"
        )

        # Expose the eligible window for the evaluation phase (and for logs).
        try:
            self.round_candidate_uids = list(candidate_uids)
        except Exception:
            pass

        # Log a compact summary of candidate stakes.
        try:
            sample = candidate_uids[:10]
            sample_str = ", ".join(f"{uid}:{float(stakes[uid]) if uid < len(stakes) else 0.0:.4f}" for uid in sample)
            bt.logging.info(f"[handshake] Candidates meeting MIN_MINER_STAKE_ALPHA={min_stake:.4f}: {len(candidate_uids)} miners (sample: {sample_str})")
        except Exception:
            pass

        # Build axon list aligned with candidate_uids.
        try:
            miner_axons = [metagraph.axons[uid] for uid in candidate_uids]
        except Exception as exc:
            bt.logging.warning(f"Failed to resolve miner axons for handshake: {exc}")
            return

        round_id = str(getattr(self, "current_round_id", "") or getattr(self.round_manager, "round_number", ""))
        validator_id = str(getattr(self, "uid", "unknown"))

        start_synapse = StartRoundSynapse(
            version=getattr(self, "version", ""),
            round_id=round_id,
            validator_id=validator_id,
            note="autoppia-web-agents-subnet",
        )

        responses = await send_start_round_synapse_to_miners(
            validator=self,
            miner_axons=miner_axons,
            start_synapse=start_synapse,
            timeout=60,
        )

        new_agents_count = 0
        current_round = int(getattr(self.round_manager, "round_number", 0) or 0)
        repo_to_count: dict[str, int] = {}
        repo_owner_by_season = getattr(self, "_season_repo_owners", None)
        if not isinstance(repo_owner_by_season, dict):
            repo_owner_by_season = {}
            self._season_repo_owners = repo_owner_by_season
        active_handshake_uids: list[int] = []
        responded_count = 0
        response_missing_count = 0
        restored_from_pending_count = 0
        missing_handshake_field_count = 0
        invalid_repo_count = 0
        repo_cap_skip_count = 0
        cooldown_skip_count = 0
        unchanged_commit_skip_count = 0
        queued_for_eval_count = 0
        self.miners_reused_this_round = set()
        self.handshake_results: dict[int, str] = {}
        self.eligibility_status_by_uid: dict[int, str] = {}
        # Diagnostics for handshake transport/payload quality.
        transport_status_counts: Counter[str] = Counter()
        transport_status_message_counts: Counter[str] = Counter()
        missing_name_count = 0
        missing_github_count = 0
        missing_both_count = 0
        missing_fields_due_transport_count = 0
        missing_fields_on_200_count = 0
        valid_handshake_payload_count = 0
        handshake_issue_rows: list[dict[str, object]] = []

        for idx, uid in enumerate(candidate_uids):
            resp = responses[idx] if idx < len(responses) else None
            if resp is None:
                response_missing_count += 1
                self.handshake_results[int(uid)] = "no_response"
                self.eligibility_status_by_uid[int(uid)] = "no_response"
                handshake_issue_rows.append(
                    {
                        "uid": int(uid),
                        "status_code": None,
                        "status_message": "no_response",
                        "has_agent_name": False,
                        "has_github_url": False,
                        "reason": "no_response",
                    }
                )
                # If we have a pending submission recorded during cooldown, we
                # can evaluate it once the cooldown expires even if the miner
                # fails to respond in this round.
                existing = self.agents_dict.get(uid)
                if isinstance(existing, AgentInfo) and existing.pending_github_url:
                    if not _is_cooldown_active(
                        current_round=current_round,
                        last_evaluated_round=getattr(existing, "last_evaluated_round", None),
                        miner_score=getattr(existing, "score", 0.0),
                        best_score_ever=getattr(self, "_best_score_ever", None),
                        handshake_responded=False,
                    ):
                        pending_info = AgentInfo(
                            uid=uid,
                            agent_name=existing.pending_agent_name or existing.agent_name,
                            agent_image=existing.pending_agent_image or existing.agent_image,
                            github_url=existing.pending_github_url,
                            normalized_repo=existing.pending_normalized_repo,
                            git_commit=None,
                        )
                        self.agents_queue.put(pending_info)
                        new_agents_count += 1
                        queued_for_eval_count += 1
                        restored_from_pending_count += 1
                continue

            responded_count += 1
            _d = getattr(resp, "dendrite", None)
            _status_code = getattr(_d, "status_code", None)
            _status_message = getattr(_d, "status_message", None)
            _status_code_key = str(_status_code) if _status_code is not None else "none"
            transport_status_counts[_status_code_key] += 1
            transport_status_message_counts[f"{_status_code_key}:{_status_message}"] += 1

            agent_name = getattr(resp, "agent_name", None)
            raw_github_url = getattr(resp, "github_url", None)
            agent_image = getattr(resp, "agent_image", None)
            has_agent_name = bool(str(agent_name).strip()) if agent_name is not None else False
            has_github_url = bool(str(raw_github_url).strip()) if raw_github_url is not None else False
            if not has_agent_name:
                missing_name_count += 1
            if not has_github_url:
                missing_github_count += 1
            if not has_agent_name and not has_github_url:
                missing_both_count += 1

            if has_agent_name and has_github_url and _status_code == 200:
                valid_handshake_payload_count += 1

            if not agent_name or not raw_github_url:
                if _status_code == 200:
                    missing_fields_on_200_count += 1
                else:
                    missing_fields_due_transport_count += 1

                if _status_code == 408:
                    _reason = "transport_timeout"
                elif _status_code and _status_code != 200:
                    _reason = f"transport_status_{_status_code}"
                elif not has_agent_name and not has_github_url:
                    _reason = "missing_agent_name_and_github_url"
                elif not has_agent_name:
                    _reason = "missing_agent_name"
                else:
                    _reason = "missing_github_url"

                handshake_issue_rows.append(
                    {
                        "uid": int(uid),
                        "status_code": _status_code,
                        "status_message": _status_message,
                        "has_agent_name": has_agent_name,
                        "has_github_url": has_github_url,
                        "reason": _reason,
                    }
                )

                # Debug: log first occurrence so we can see what the validator actually received
                if missing_handshake_field_count == 0:
                    try:
                        _dump = getattr(resp, "model_dump", None)
                        _dump = _dump() if callable(_dump) else getattr(resp, "__dict__", {})
                        _keys = list(_dump.keys()) if isinstance(_dump, dict) else []
                        bt.logging.warning(
                            f"[handshake] DEBUG first missing_fields: uid={uid} "
                            f"agent_name={repr(agent_name)} github_url={repr(raw_github_url)} "
                            f"resp_type={type(resp).__name__} status_code={_status_code} "
                            f"status_message={_status_message!r} dump_keys={_keys}"
                        )
                    except Exception as _e:
                        bt.logging.warning(f"[handshake] DEBUG first missing_fields uid={uid} error={_e}")
                # Strict: an explicit submission is required. Treat missing fields
                # as an invalid submission for this uid.
                existing = self.agents_dict.get(uid)
                if isinstance(existing, AgentInfo):
                    try:
                        existing.agent_name = agent_name or getattr(existing, "agent_name", "")
                        existing.agent_image = agent_image
                        existing.github_url = raw_github_url or ""
                        existing.normalized_repo = None
                        existing.git_commit = None
                        existing.score = 0.0
                        existing.evaluated = True
                    except Exception:
                        pass
                    self.agents_dict[uid] = existing
                else:
                    self.agents_dict[uid] = AgentInfo(
                        uid=uid,
                        agent_name=agent_name or "",
                        agent_image=agent_image,
                        github_url=raw_github_url or "",
                        normalized_repo=None,
                        git_commit=None,
                        score=0.0,
                        evaluated=True,
                    )
                    if self.round_manager.round_number == 1:
                        self.agents_on_first_handshake.append(uid)
                missing_handshake_field_count += 1
                # Keep handshake_results aligned with transport diagnostics:
                # when transport failed (non-200), persist transport reason;
                # otherwise persist semantic missing-field reason.
                if _reason.startswith("transport_"):
                    self.handshake_results[int(uid)] = _reason
                elif not agent_name:
                    self.handshake_results[int(uid)] = "missing_agent_name"
                elif not raw_github_url:
                    self.handshake_results[int(uid)] = "missing_github_url"
                else:
                    self.handshake_results[int(uid)] = "missing_fields"
                self.eligibility_status_by_uid[int(uid)] = self.handshake_results[int(uid)]
                continue

            if max_by_coldkey > 0:
                response_coldkey = ""
                if 0 <= uid < len(coldkeys):
                    raw_coldkey = coldkeys[uid]
                    if raw_coldkey:
                        response_coldkey = str(raw_coldkey).strip()
                response_coldkey = response_coldkey or f"__coldkey_unknown__:{uid}"

                if coldkey_counts.get(response_coldkey, 0) >= max_by_coldkey:
                    bt.logging.warning(f"[handshake] Skipping uid={uid} due MAX_MINERS_PER_COLDKEY={max_by_coldkey} (post-handshake)")
                    existing = self.agents_dict.get(uid)
                    if isinstance(existing, AgentInfo):
                        try:
                            existing.score = 0.0
                            existing.evaluated = True
                        except Exception:
                            pass
                        self.agents_dict[uid] = existing
                    else:
                        self.agents_dict[uid] = AgentInfo(
                            uid=uid,
                            agent_name=agent_name or "",
                            agent_image=agent_image,
                            github_url=raw_github_url or "",
                            normalized_repo=None,
                            git_commit=None,
                            score=0.0,
                            evaluated=True,
                        )
                    if self.round_manager.round_number == 1:
                        self.agents_on_first_handshake.append(uid)
                    coldkey_cap_skip_count += 1
                    self.handshake_results[int(uid)] = "coldkey_cap"
                    self.eligibility_status_by_uid[int(uid)] = "coldkey_cap"
                    continue

                coldkey_counts[response_coldkey] = coldkey_counts.get(response_coldkey, 0) + 1

            # Store handshake payload for IWAP registration
            if not isinstance(getattr(self, "round_handshake_payloads", None), dict):
                self.round_handshake_payloads = {}
            self.round_handshake_payloads[int(uid)] = resp

            normalized_repo, ref = normalize_and_validate_github_url(
                raw_github_url,
                miner_uid=uid,
                require_ref=True,
            )

            # Strict submission policy: if miner didn't provide a valid repo + ref/commit URL,
            # mark as evaluated with zero and do not enqueue expensive evaluation work.
            if normalized_repo is None:
                existing = self.agents_dict.get(uid)
                if isinstance(existing, AgentInfo):
                    try:
                        existing.agent_name = agent_name
                        existing.agent_image = agent_image
                        existing.github_url = raw_github_url or ""
                        existing.normalized_repo = None
                        existing.git_commit = None
                        existing.score = 0.0
                        existing.evaluated = True
                    except Exception:
                        pass
                    self.agents_dict[uid] = existing
                else:
                    self.agents_dict[uid] = AgentInfo(
                        uid=uid,
                        agent_name=agent_name,
                        agent_image=agent_image,
                        github_url=raw_github_url or "",
                        normalized_repo=None,
                        git_commit=None,
                        score=0.0,
                        evaluated=True,
                    )
                    if self.round_manager.round_number == 1:
                        self.agents_on_first_handshake.append(uid)
                invalid_repo_count += 1
                self.handshake_results[int(uid)] = "invalid_github_url"
                self.eligibility_status_by_uid[int(uid)] = "invalid_github_url"
                continue

            if max_by_repo > 0 and normalized_repo:
                normalized_repo_key = str(normalized_repo).strip().lower()
                owner_key = f"uid:{uid}"
                if 0 <= uid < len(coldkeys):
                    raw_owner = coldkeys[uid]
                    if raw_owner:
                        owner_key = str(raw_owner).strip()

                repo_owner_history = repo_owner_by_season.get(normalized_repo_key, set())
                if not isinstance(repo_owner_history, set):
                    repo_owner_history = set()
                repo_count = int(repo_to_count.get(normalized_repo_key, 0))
                history_count = len(repo_owner_history)
                if owner_key not in repo_owner_history and history_count >= max_by_repo:
                    bt.logging.warning(f"[handshake] Skipping uid={uid} repo={normalized_repo_key} due MAX_MINERS_PER_REPO={max_by_repo} (round={repo_count}, unique_history={history_count})")
                    existing = self.agents_dict.get(uid)
                    if isinstance(existing, AgentInfo):
                        try:
                            existing.score = 0.0
                            existing.evaluated = True
                        except Exception:
                            pass
                        self.agents_dict[uid] = existing
                    else:
                        self.agents_dict[uid] = AgentInfo(
                            uid=uid,
                            agent_name=agent_name or "",
                            agent_image=agent_image,
                            github_url=raw_github_url or "",
                            normalized_repo=normalized_repo,
                            git_commit=None,
                            score=0.0,
                            evaluated=True,
                        )
                    if self.round_manager.round_number == 1:
                        self.agents_on_first_handshake.append(uid)
                    repo_cap_skip_count += 1
                    self.handshake_results[int(uid)] = "repo_cap"
                    self.eligibility_status_by_uid[int(uid)] = "repo_cap"
                    continue

                if owner_key not in repo_owner_history:
                    repo_owner_history.add(owner_key)
                    repo_owner_by_season[normalized_repo_key] = repo_owner_history

                repo_to_count[normalized_repo_key] = repo_count + 1

            self.handshake_results[int(uid)] = "ok"
            self.eligibility_status_by_uid[int(uid)] = "handshake_valid"
            active_handshake_uids.append(int(uid))

            # Resolve commit for all (needed for unchanged check, already-evaluated check, and display).
            commit_sha: str | None = None
            if normalized_repo and ref:
                try:
                    if "/commit/" in str(raw_github_url or ""):
                        commit_sha = str(ref)
                    else:
                        commit_sha = resolve_remote_ref_commit(normalized_repo, ref)
                except Exception:
                    commit_sha = None
            if commit_sha and normalized_repo:
                commit_url = f"{normalized_repo}/commit/{commit_sha}"
            else:
                commit_url = raw_github_url

            agent_info = AgentInfo(
                uid=uid,
                agent_name=getattr(resp, "agent_name", None),
                agent_image=getattr(resp, "agent_image", None),
                github_url=commit_url,
                normalized_repo=normalized_repo,
                git_commit=commit_sha,
            )
            ColoredLogger.info(agent_info.__repr__(), ColoredLogger.GREEN)
            try:
                setattr(resp, "github_url", commit_url)
            except Exception:
                pass

            existing = self.agents_dict.get(uid)
            if isinstance(existing, AgentInfo):
                existing_repo = getattr(existing, "normalized_repo", None)
                if not existing_repo:
                    try:
                        existing_repo, _ = normalize_and_validate_github_url(getattr(existing, "github_url", None), miner_uid=uid)
                    except Exception:
                        existing_repo = None

                existing_commit = getattr(existing, "git_commit", None)

                # Do not re-evaluate if the submission commit didn't change.
                # If we cannot resolve a commit hash, be conservative and re-evaluate.
                if normalized_repo and commit_sha and existing_repo == normalized_repo and _commits_match(existing_commit, commit_sha):
                    try:
                        current_season = int(getattr(getattr(self, "season_manager", None), "season_number", 0) or 0)
                    except Exception:
                        current_season = 0
                    last_season = getattr(existing, "last_evaluated_season", None)
                    last_round = getattr(existing, "last_evaluated_round", None)
                    try:
                        last_season_i = int(last_season) if last_season is not None else None
                    except Exception:
                        last_season_i = None
                    # IMPORTANT: do not reuse unless this miner has been actually evaluated before.
                    # A previous round may have captured handshake metadata and then been skipped
                    # (late start), leaving existing commit info without a real evaluation.
                    has_prior_evaluation = bool(getattr(existing, "evaluated", False))
                    if not has_prior_evaluation:
                        has_prior_evaluation = (last_season_i is not None) or isinstance(last_round, int)
                    if current_season and last_season_i is not None and last_season_i != int(current_season):
                        # New season -> tasks changed, force re-evaluation even if commit unchanged.
                        pass
                    elif has_prior_evaluation:
                        # Keep score/evaluated, but allow display metadata to update.
                        # Use _evaluated_commits_by_miner so reused_from points to the FIRST evaluated run, not the previous round (which may be reused).
                        evaluated_map = getattr(self, "_evaluated_commits_by_miner", None) or {}
                        key = f"{normalized_repo.strip()}|{commit_sha.strip()}"
                        stored = (evaluated_map.get(uid) or {}).get(key)
                        if isinstance(stored, dict) and stored.get("agent_run_id"):
                            if not isinstance(getattr(self, "reused_from_agent_run_id_by_uid", None), dict):
                                self.reused_from_agent_run_id_by_uid = {}
                            if not isinstance(getattr(self, "reused_stats_by_uid", None), dict):
                                self.reused_stats_by_uid = {}
                            self.reused_from_agent_run_id_by_uid[uid] = str(stored["agent_run_id"])
                            self.reused_stats_by_uid[uid] = {k: v for k, v in stored.items() if k != "agent_run_id"}
                        try:
                            existing.agent_name = agent_info.agent_name
                            existing.agent_image = agent_info.agent_image
                            existing.github_url = agent_info.github_url
                            if not getattr(existing, "normalized_repo", None):
                                existing.normalized_repo = normalized_repo
                            # Clear any stale pending submission (we are already on this commit).
                            existing.pending_github_url = None
                            existing.pending_agent_name = None
                            existing.pending_agent_image = None
                            existing.pending_normalized_repo = None
                            existing.pending_ref = None
                            existing.pending_received_round = None
                        except Exception:
                            pass
                        self.agents_dict[uid] = existing
                        unchanged_commit_skip_count += 1
                        self.miners_reused_this_round.add(uid)
                        self.eligibility_status_by_uid[int(uid)] = "reused"
                        continue
                    else:
                        bt.logging.debug(f"[reuse] Miner {uid}: unchanged commit but no prior evaluation metadata; enqueueing for evaluation.")

                # Already evaluated this (repo, commit) in a past round: do not re-evaluate.
                if normalized_repo and commit_sha:
                    evaluated_map = getattr(self, "_evaluated_commits_by_miner", None) or {}
                    key = f"{normalized_repo.strip()}|{commit_sha.strip()}"
                    stored = (evaluated_map.get(uid) or {}).get(key)
                    if isinstance(stored, dict) and stored.get("agent_run_id"):
                        if not isinstance(getattr(self, "reused_from_agent_run_id_by_uid", None), dict):
                            self.reused_from_agent_run_id_by_uid = {}
                        if not isinstance(getattr(self, "reused_stats_by_uid", None), dict):
                            self.reused_stats_by_uid = {}
                        ref_run_id = str(stored["agent_run_id"])
                        self.reused_from_agent_run_id_by_uid[uid] = ref_run_id
                        self.reused_stats_by_uid[uid] = {k: v for k, v in stored.items() if k != "agent_run_id"}
                        self.miners_reused_this_round.add(uid)
                        self.eligibility_status_by_uid[int(uid)] = "reused"
                        bt.logging.info(f"[reuse] Miner {uid}: same (repo, commit) as previous run {ref_run_id}; reusing results (no re-eval).")
                        try:
                            existing.agent_name = agent_info.agent_name
                            existing.agent_image = agent_info.agent_image
                            existing.github_url = agent_info.github_url
                            if not getattr(existing, "normalized_repo", None):
                                existing.normalized_repo = normalized_repo
                        except Exception:
                            pass
                        self.agents_dict[uid] = existing
                        unchanged_commit_skip_count += 1
                        continue

                # Submission changed (or unknown): enqueue for evaluation, but do
                # not clobber the previously evaluated score/commit until new
                # evaluation completes.
                if _is_cooldown_active(
                    current_round=current_round,
                    last_evaluated_round=getattr(existing, "last_evaluated_round", None),
                    miner_score=getattr(existing, "score", 0.0),
                    best_score_ever=getattr(self, "_best_score_ever", None),
                    handshake_responded=True,
                ):
                    # Store pending submission and skip enqueuing for now.
                    try:
                        existing.pending_github_url = agent_info.github_url
                        existing.pending_agent_name = agent_info.agent_name
                        existing.pending_agent_image = agent_info.agent_image
                        existing.pending_normalized_repo = agent_info.normalized_repo
                        existing.pending_ref = ref
                        existing.pending_received_round = current_round
                    except Exception:
                        pass
                    self.agents_dict[uid] = existing
                    cooldown_skip_count += 1
                    self.eligibility_status_by_uid[int(uid)] = "handshake_valid"
                    continue

                self.agents_queue.put(agent_info)
                new_agents_count += 1
                queued_for_eval_count += 1
                self.eligibility_status_by_uid[int(uid)] = "handshake_valid"
                continue

            # New uid (e.g. after validator restart): still check if this
            # (repo, commit) was already evaluated in this season.
            if normalized_repo and commit_sha:
                evaluated_map = getattr(self, "_evaluated_commits_by_miner", None) or {}
                key = f"{normalized_repo.strip()}|{commit_sha.strip()}"
                stored = (evaluated_map.get(uid) or {}).get(key)
                if isinstance(stored, dict) and stored.get("agent_run_id"):
                    if not isinstance(getattr(self, "reused_from_agent_run_id_by_uid", None), dict):
                        self.reused_from_agent_run_id_by_uid = {}
                    if not isinstance(getattr(self, "reused_stats_by_uid", None), dict):
                        self.reused_stats_by_uid = {}
                    ref_run_id = str(stored["agent_run_id"])
                    self.reused_from_agent_run_id_by_uid[uid] = ref_run_id
                    self.reused_stats_by_uid[uid] = {k: v for k, v in stored.items() if k != "agent_run_id"}
                    self.miners_reused_this_round.add(uid)
                    self.eligibility_status_by_uid[int(uid)] = "reused"
                    bt.logging.info(f"[reuse] Miner {uid}: same (repo, commit) as previous run {ref_run_id}; reusing results (no re-eval).")
                    self.agents_dict[uid] = agent_info
                    unchanged_commit_skip_count += 1
                    continue

            # New uid: track it immediately and enqueue for evaluation.
            self.agents_dict[uid] = agent_info
            self.agents_queue.put(agent_info)
            if self.round_manager.round_number == 1:
                self.agents_on_first_handshake.append(uid)
            new_agents_count += 1
            queued_for_eval_count += 1
            self.eligibility_status_by_uid[int(uid)] = "handshake_valid"
        bt.logging.info(
            "[handshake] complete "
            f"min_stake={min_stake:.4f} "
            f"responded={responded_count}/{len(responses)} "
            f"missing_response={response_missing_count} "
            f"queued_for_eval={queued_for_eval_count} "
            f"restored_from_pending={restored_from_pending_count} "
            f"missing_fields={missing_handshake_field_count} "
            f"coldkey_cap_skip={coldkey_cap_skip_count} "
            f"invalid_repo={invalid_repo_count} "
            f"repo_cap_skip={repo_cap_skip_count} "
            f"cooldown_skip={cooldown_skip_count} "
            f"unchanged_commit={unchanged_commit_skip_count} "
            f"new_agents={new_agents_count}"
        )
        bt.logging.info(
            "[handshake] transport/payload summary "
            f"valid_payloads={valid_handshake_payload_count}/{len(candidate_uids)} "
            f"status_408_timeout={transport_status_counts.get('408', 0)} "
            f"status_503={transport_status_counts.get('503', 0)} "
            f"status_504={transport_status_counts.get('504', 0)} "
            f"missing_name={missing_name_count} "
            f"missing_github={missing_github_count} "
            f"missing_both={missing_both_count} "
            f"missing_due_transport={missing_fields_due_transport_count} "
            f"missing_on_200={missing_fields_on_200_count}"
        )

        # Persist detailed handshake diagnostics for post-mortem analysis.
        try:
            season_number = int(getattr(getattr(self, "season_manager", None), "season_number", 0) or 0)
        except Exception:
            season_number = 0
        try:
            round_number = int(getattr(getattr(self, "round_manager", None), "round_number", 0) or 0)
        except Exception:
            round_number = 0
        round_id = str(getattr(self, "current_round_id", "") or f"round_{round_number}")
        season_label = str(season_number if season_number > 0 else "unknown")
        round_label = str(round_number if round_number > 0 else "unknown")
        root_getter = getattr(self, "_state_summary_root", None)
        base_dir = root_getter() if callable(root_getter) else Path("data")
        handshake_dir = Path(base_dir) / f"season_{season_label}" / f"round_{round_label}" / "handshake"
        handshake_dir.mkdir(parents=True, exist_ok=True)
        handshake_report_path = handshake_dir / f"{round_id}_handshake_diagnostics.json"
        handshake_payload = {
            "round_id": round_id,
            "season_number": season_number,
            "round_number": round_number,
            "generated_at_unix": time.time(),
            "summary": {
                "total_candidates": len(candidate_uids),
                "responses_objects_received": responded_count,
                "no_response": response_missing_count,
                "valid_payloads": valid_handshake_payload_count,
                "missing_name": missing_name_count,
                "missing_github": missing_github_count,
                "missing_both": missing_both_count,
                "missing_due_transport": missing_fields_due_transport_count,
                "missing_on_200": missing_fields_on_200_count,
                "status_counts": dict(transport_status_counts),
                "status_message_top10": transport_status_message_counts.most_common(10),
            },
            "issues": handshake_issue_rows,
        }
        try:
            handshake_report_path.write_text(
                json.dumps(handshake_payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            bt.logging.info(f"[handshake] diagnostics saved: {handshake_report_path}")
        except Exception as exc:
            bt.logging.warning(f"[handshake] failed to save diagnostics JSON: {exc}")

        # Only miners that responded this round should be treated as "active"
        # for IWAP registration and per-round reporting. Keeping this bounded
        # avoids expensive IWAP loops when we handshake a wide UID window.
        self.active_miner_uids = active_handshake_uids

    async def _wait_for_minimum_start_block(self) -> bool:
        """
        Block until the chain height reaches the configured launch gate.

        Returns True when a wait occurred so callers can short-circuit their flow.
        """
        rm = getattr(self, "round_manager", None)
        if rm is None:
            raise RuntimeError("Round manager not initialized; cannot enforce minimum start block")

        current_block = self.block
        if rm.can_start_round(current_block):
            return False

        # Best effort: while waiting for the launch gate, keep runtime config in IWAP
        # synchronized (main validator updates DB; non-main calls are ignored server-side).
        await self._sync_runtime_config_while_waiting(current_block=current_block)

        blocks_remaining = rm.blocks_until_allowed(current_block)
        seconds_remaining = blocks_remaining * rm.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60
        hours_remaining = minutes_remaining / 60

        current_epoch = rm.block_to_epoch(current_block)
        target_epoch = rm.block_to_epoch(int(rm.minimum_start_block))

        eta = f"~{hours_remaining:.1f}h" if hours_remaining >= 1 else f"~{minutes_remaining:.0f}m"
        bt.logging.warning(f"🔒 Locked until block {int(rm.minimum_start_block):,} (epoch {target_epoch:.2f}) | now {current_block:,} (epoch {current_epoch:.2f}) | ETA {eta}")

        wait_seconds = min(max(seconds_remaining, 30), 600)
        rm.enter_phase(
            RoundPhase.WAITING,
            block=current_block,
            note=f"Waiting for minimum start block {int(rm.minimum_start_block)}",
        )
        bt.logging.warning(f"💤 Rechecking in {wait_seconds:.0f}s...")

        await asyncio.sleep(wait_seconds)
        return True

    def _apply_runtime_config(self, payload: dict) -> bool:
        round_cfg = payload.get("config_season_round") if isinstance(payload, dict) else None
        if not isinstance(round_cfg, dict):
            return False

        rm = getattr(self, "round_manager", None)
        sm = getattr(self, "season_manager", None)
        if rm is None or sm is None:
            return False

        try:
            minimum_start_block = int(round_cfg["minimum_start_block"])
            round_size_epochs = float(round_cfg["round_size_epochs"])
            season_size_epochs = float(round_cfg["season_size_epochs"])
        except (KeyError, TypeError, ValueError):
            return False

        rm.minimum_start_block = minimum_start_block
        rm.round_size_epochs = round_size_epochs
        rm.round_block_length = int(rm.BLOCKS_PER_EPOCH * rm.round_size_epochs)

        sm.minimum_start_block = minimum_start_block
        sm.season_size_epochs = season_size_epochs
        sm.season_block_length = int(sm.BLOCKS_PER_EPOCH * sm.season_size_epochs)
        return True

    async def _hydrate_runtime_config_from_iwap(self) -> None:
        iwap_client = getattr(self, "iwap_client", None)
        if iwap_client is None:
            return

        fetch_method = getattr(iwap_client, "fetch_runtime_config", None)
        if not callable(fetch_method):
            return

        try:
            payload = await fetch_method()
            if self._apply_runtime_config(payload):
                round_cfg = payload.get("config_season_round") or {}
                bt.logging.info(
                    "🧩 IWAP runtime-config loaded | "
                    f"minimum_start_block={round_cfg.get('minimum_start_block')} "
                    f"round_size_epochs={round_cfg.get('round_size_epochs')} "
                    f"season_size_epochs={round_cfg.get('season_size_epochs')}"
                )
        except Exception as exc:
            bt.logging.warning(f"runtime-config fetch at startup failed (continuing): {type(exc).__name__}: {exc}")

    async def _sync_runtime_config_while_waiting(self, *, current_block: int) -> None:
        """
        Best-effort runtime-config sync while validator is in pre-start waiting phase.
        This prevents IWAP from staying without config_season_round/minimum_validator_version
        when the main validator has not started round execution yet.
        """
        iwap_client = getattr(self, "iwap_client", None)
        if iwap_client is None:
            return

        sync_method = getattr(iwap_client, "sync_runtime_config", None)
        if not callable(sync_method):
            return

        now = float(time.time())
        interval_seconds = 300.0
        last_attempt = float(getattr(self, "_runtime_config_wait_sync_last_attempt_ts", 0.0) or 0.0)
        if (now - last_attempt) < interval_seconds:
            return
        self._runtime_config_wait_sync_last_attempt_ts = now

        validator_identity_builder = getattr(self, "_build_validator_identity", None)
        validator_snapshot_builder = getattr(self, "_build_validator_snapshot", None)
        if not callable(validator_identity_builder) or not callable(validator_snapshot_builder):
            return

        try:
            validator_identity = validator_identity_builder()
            waiting_round_id = f"runtime_sync_waiting_{int(current_block)}"
            validator_snapshot = validator_snapshot_builder(waiting_round_id)
            response = await sync_method(
                validator_identity=validator_identity,
                validator_snapshot=validator_snapshot,
            )
            updated = bool(response.get("updated")) if isinstance(response, dict) else False
            if updated:
                bt.logging.info(f"🧩 IWAP runtime-config synced during wait (main update applied) | block={current_block:,}")
            else:
                bt.logging.info(f"🧩 IWAP runtime-config sync during wait acknowledged (non-main/no-op) | block={current_block:,}")
        except Exception as exc:
            bt.logging.warning(f"runtime-config sync during wait failed (continuing): {type(exc).__name__}: {exc}")
