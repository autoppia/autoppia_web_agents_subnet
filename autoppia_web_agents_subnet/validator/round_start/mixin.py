from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
import bittensor as bt

from autoppia_web_agents_subnet.utils.log_colors import round_details_tag
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

from autoppia_web_agents_subnet.validator.models import AgentInfo
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.round_start.types import RoundStartResult
from autoppia_web_agents_subnet.opensource.utils_git import (
    normalize_and_validate_github_url,
    resolve_remote_ref_commit,
)
from autoppia_web_agents_subnet.validator.config import (
    MINIMUM_START_BLOCK,
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION,
    MIN_MINER_STAKE_ALPHA,
    MAX_MINERS_PER_ROUND_BY_STAKE,
    MAX_MINERS_PER_COLDKEY,
    MAX_MINERS_PER_REPO,
    EVALUATION_COOLDOWN_MIN_ROUNDS,
    EVALUATION_COOLDOWN_MAX_ROUNDS,
    EVALUATION_COOLDOWN_NO_RESPONSE_BADNESS,
    EVALUATION_COOLDOWN_ZERO_SCORE_BADNESS,
)
from autoppia_web_agents_subnet.utils.commitments import read_all_plain_commitments
from autoppia_web_agents_subnet.validator.payment.config import (
    ALPHA_PER_EVAL, PAYMENT_WALLET_SS58, PAYMENT_CACHE_PATH,
)
from autoppia_web_agents_subnet.validator.payment.helpers import (
    get_alpha_sent_by_miner, get_all_consumed_evals, get_consumed_evals,
    remaining_evaluations, set_all_consumed_evals,
)


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

        return RoundStartResult(
            continue_forward=True,
            reason="Round Started Successfully",
        )

    async def _collect_miner_commitments(self) -> None:
        """
        Read miner agent metadata from on-chain commitments and build the
        evaluation queue for this round.

        Replaces the old synapse-based handshake: instead of broadcasting
        ``StartRoundSynapse`` to miners and waiting for responses, commitments
        written by ``autoppia-miner-cli submit`` are read directly from chain.
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
            bt.logging.warning("No metagraph on validator; skipping miner commitment collection")
            return

        n = int(getattr(metagraph, "n", 0) or 0)
        if n <= 0:
            bt.logging.warning("Metagraph has no peers; skipping miner commitment collection")
            return

        # Resolve stakes if present; otherwise treat as zero.
        try:
            stakes = list(getattr(metagraph, "stake", [0.0] * n))
        except Exception:
            stakes = [0.0] * n
        coldkeys = list(getattr(metagraph, "coldkeys", []))
        hotkeys = list(getattr(metagraph, "hotkeys", []))
        max_by_coldkey = int(MAX_MINERS_PER_COLDKEY)
        max_by_repo = int(MAX_MINERS_PER_REPO)

        validator_uid = int(getattr(self, "uid", 0) or 0)
        min_stake = float(MIN_MINER_STAKE_ALPHA)

        # ── Candidate selection (same pipeline as before) ─────────────────
        candidate_uids: list[int] = []
        candidate_stakes: list[tuple[float, int, str]] = []
        skipped_below_stake = 0
        skipped_coldkey_cap = 0
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
                bt.logging.debug(f"[collect_commitments] Skipping uid={uid} stake={stake_val:.4f} < MIN_MINER_STAKE_ALPHA={min_stake:.4f}")

        if not candidate_stakes:
            bt.logging.warning(f"No miners meet MIN_MINER_STAKE_ALPHA={min_stake:.4f}; active_miner_uids will be empty")
            return

        candidates_after_stake = len(candidate_stakes)

        # Sort by stake before capping per coldkey and per round.
        candidate_stakes.sort(key=lambda item: float(item[0]), reverse=True)

        # Optional: cap miner selection per coldkey to avoid one coldkey taking the whole window.
        if max_by_coldkey > 0:
            coldkey_counts: dict[str, int] = {}
            filtered_candidates: list[int] = []
            for _, uid, coldkey in candidate_stakes:
                key = coldkey or f"__coldkey_unknown__:{uid}"
                if coldkey_counts.get(key, 0) >= max_by_coldkey:
                    skipped_coldkey_cap += 1
                    bt.logging.warning(f"[collect_commitments] Skipping uid={uid} due MAX_MINERS_PER_COLDKEY={max_by_coldkey}")
                    continue
                coldkey_counts[key] = coldkey_counts.get(key, 0) + 1
                filtered_candidates.append(uid)
            candidate_uids = filtered_candidates
        else:
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
            "[collect_commitments] Candidate selection summary "
            f"total={n - 1}|eligible_by_stake={candidates_after_stake}|"
            f"below_stake={skipped_below_stake}|"
            f"coldkey_cap_skip={skipped_coldkey_cap}|stake_cap_skip={skipped_stake_cap}|"
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
            bt.logging.info(f"[collect_commitments] Candidates meeting MIN_MINER_STAKE_ALPHA={min_stake:.4f}: {len(candidate_uids)} miners (sample: {sample_str})")
        except Exception:
            pass

        # ── Read all on-chain commitments ─────────────────────────────────
        netuid = int(getattr(self.config, "netuid", 36) or 36)
        st = await self._get_async_subtensor()
        try:
            all_commitments = await read_all_plain_commitments(st, netuid=netuid)
        except Exception as exc:
            bt.logging.error(f"[collect_commitments] Failed to read on-chain commitments: {exc}")
            all_commitments = {}

        # Build hotkey → uid lookup from metagraph.
        hotkey_to_uid: dict[str, int] = {}
        for uid_idx in range(len(hotkeys)):
            hk = hotkeys[uid_idx]
            if hk:
                hotkey_to_uid[str(hk).strip()] = uid_idx

        # Index commitments by uid (only miner-type commitments).
        commitment_by_uid: dict[int, dict] = {}
        for hk, data in all_commitments.items():
            if not isinstance(data, dict):
                continue
            if data.get("t") != "m":
                continue
            uid = hotkey_to_uid.get(str(hk).strip())
            if uid is not None:
                commitment_by_uid[uid] = data

        bt.logging.info(
            f"[collect_commitments] On-chain: {len(all_commitments)} total commitments, "
            f"{len(commitment_by_uid)} miner commitments matched to UIDs"
        )

        # Crash recovery: restore consumed evals from on-chain commitment "e" field.
        if bool(PAYMENT_WALLET_SS58) and float(ALPHA_PER_EVAL) > 0:
            try:
                my_commitment = all_commitments.get(self.wallet.hotkey.ss58_address)
                if isinstance(my_commitment, dict) and "e" in my_commitment:
                    sm_cr = getattr(self, "season_manager", None)
                    s_start_cr = int(sm_cr.get_season_start_block(self.block)) if sm_cr else None
                    s_dur_cr = int(getattr(sm_cr, "season_block_length", 0) or 0) if sm_cr else None
                    if not s_dur_cr:
                        from autoppia_web_agents_subnet.validator.config import SEASON_SIZE_EPOCHS
                        bpe = getattr(getattr(self, "round_manager", None), "BLOCKS_PER_EPOCH", 360) or 360
                        s_dur_cr = int(float(SEASON_SIZE_EPOCHS) * int(bpe))
                    if s_start_cr is not None and s_dur_cr and s_dur_cr > 0:
                        cache_kw = dict(payment_address=PAYMENT_WALLET_SS58, netuid=netuid,
                                        season_start_block=s_start_cr, season_duration_blocks=s_dur_cr,
                                        cache_path=PAYMENT_CACHE_PATH)
                        local_consumed = get_all_consumed_evals(**cache_kw)
                        onchain_consumed = my_commitment["e"]
                        if isinstance(onchain_consumed, dict) and not local_consumed:
                            set_all_consumed_evals(onchain_consumed, **cache_kw)
                            bt.logging.info(f"[payment] Restored {len(onchain_consumed)} consumed eval entries from on-chain")
                        elif isinstance(onchain_consumed, dict) and local_consumed:
                            merged, updated = dict(local_consumed), False
                            for ck, count in onchain_consumed.items():
                                if not isinstance(ck, str):
                                    continue
                                try:
                                    onchain_val = int(count or 0)
                                except Exception:
                                    continue
                                if onchain_val > int(merged.get(ck, 0) or 0):
                                    merged[ck] = onchain_val
                                    updated = True
                            if updated:
                                set_all_consumed_evals(merged, **cache_kw)
                                bt.logging.info("[payment] Merged consumed evals from on-chain (some on-chain values were higher)")
            except Exception as exc:
                bt.logging.warning(f"[payment] Consumed evals crash recovery failed: {exc}")

        # Pre-compute per-coldkey remaining evaluations for payment gating.
        payment_enabled = bool(PAYMENT_WALLET_SS58) and float(ALPHA_PER_EVAL) > 0
        remaining_evals_by_coldkey: dict[str, int] = {}
        if payment_enabled:
            try:
                sm = getattr(self, "season_manager", None)
                s_start = int(sm.get_season_start_block(self.block)) if sm else None
                s_duration = int(getattr(sm, "season_block_length", 0) or 0) if sm else None
                if not s_duration:
                    from autoppia_web_agents_subnet.validator.config import SEASON_SIZE_EPOCHS
                    bpe = getattr(getattr(self, "round_manager", None), "BLOCKS_PER_EPOCH", 360) or 360
                    s_duration = int(float(SEASON_SIZE_EPOCHS) * int(bpe))
                if s_start is not None and s_duration and s_duration > 0:
                    unique_coldkeys: set[str] = set()
                    for uid in candidate_uids:
                        if 0 <= uid < len(coldkeys):
                            ck = str(coldkeys[uid] or "").strip()
                            if ck:
                                unique_coldkeys.add(ck)
                    pay_kw = dict(payment_address=PAYMENT_WALLET_SS58, netuid=netuid,
                                  season_start_block=s_start, season_duration_blocks=s_duration,
                                  cache_path=PAYMENT_CACHE_PATH)
                    for ck in unique_coldkeys:
                        try:
                            paid_rao = await get_alpha_sent_by_miner(ck, subtensor=self.subtensor, **pay_kw)
                            consumed = get_consumed_evals(ck, **pay_kw)
                            remaining_evals_by_coldkey[ck] = remaining_evaluations(paid_rao, consumed)
                        except Exception as exc:
                            bt.logging.warning(f"[collect_commitments] Payment check failed for {ck[:12]}...: {exc}")
                            remaining_evals_by_coldkey[ck] = 999_999  # Fail-open
                    paid_count = sum(1 for r in remaining_evals_by_coldkey.values() if r > 0)
                    bt.logging.info(f"[collect_commitments] Payment balance: {len(unique_coldkeys)} coldkeys scanned, {paid_count} have remaining evals")
            except Exception as exc:
                bt.logging.warning(f"[collect_commitments] Payment balance setup failed: {exc}; proceeding without gating")
                payment_enabled = False

        # ── Process each candidate ────────────────────────────────────────
        new_agents_count = 0
        current_round = int(getattr(self.round_manager, "round_number", 0) or 0)
        repo_to_count: dict[str, int] = {}
        repo_owner_by_season = getattr(self, "_season_repo_owners", None)
        if not isinstance(repo_owner_by_season, dict):
            repo_owner_by_season = {}
            self._season_repo_owners = repo_owner_by_season
        active_miner_uids_list: list[int] = []
        no_commitment_count = 0
        restored_from_pending_count = 0
        missing_field_count = 0
        invalid_repo_count = 0
        repo_cap_skip_count = 0
        cooldown_skip_count = 0
        unchanged_commit_skip_count = 0
        queued_for_eval_count = 0
        payment_skip_count = 0

        def _check_payment_balance(uid: int) -> bool:
            if not payment_enabled:
                return True
            ck = str(coldkeys[uid] or "").strip() if 0 <= uid < len(coldkeys) else ""
            if not ck:
                return True
            remaining = remaining_evals_by_coldkey.get(ck)
            return remaining is None or remaining > 0

        for uid in candidate_uids:
            commitment = commitment_by_uid.get(uid)

            # No on-chain commitment for this uid.
            if commitment is None:
                no_commitment_count += 1
                # Check for pending submission from a previous cooldown.
                existing = self.agents_dict.get(uid)
                if isinstance(existing, AgentInfo) and existing.pending_github_url:
                    if not _is_cooldown_active(
                        current_round=current_round,
                        last_evaluated_round=getattr(existing, "last_evaluated_round", None),
                        miner_score=getattr(existing, "score", 0.0),
                        best_score_ever=getattr(self, "_best_score_ever", None),
                        handshake_responded=False,
                    ):
                        if not _check_payment_balance(uid):
                            bt.logging.info(f"[collect_commitments] Skipping uid={uid} (pending restore): no remaining paid evals")
                            payment_skip_count += 1
                            continue
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

            # Extract fields from commitment payload.
            agent_name = str(commitment.get("n") or "").strip() or None
            raw_github_url = str(commitment.get("g") or "").strip() or None
            agent_image = str(commitment.get("i") or "").strip() or None

            if not agent_name or not raw_github_url:
                # Strict: an explicit submission is required.
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
                missing_field_count += 1
                continue

            # Miner has a valid commitment; treat as active for IWAP.
            active_miner_uids_list.append(int(uid))

            # Store a payload namespace for IWAP registration (replaces synapse).
            if not isinstance(getattr(self, "round_handshake_payloads", None), dict):
                self.round_handshake_payloads = {}
            self.round_handshake_payloads[int(uid)] = SimpleNamespace(
                agent_name=agent_name,
                github_url=raw_github_url,
                agent_image=agent_image,
                note=None,
            )

            normalized_repo, ref = normalize_and_validate_github_url(
                raw_github_url,
                miner_uid=uid,
                require_ref=True,
            )

            # Strict submission policy: invalid repo + ref → zero score, no eval.
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
                    bt.logging.warning(f"[collect_commitments] Skipping uid={uid} repo={normalized_repo_key} due MAX_MINERS_PER_REPO={max_by_repo} (round={repo_count}, unique_history={history_count})")
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
                    continue

                if owner_key not in repo_owner_history:
                    repo_owner_history.add(owner_key)
                    repo_owner_by_season[normalized_repo_key] = repo_owner_history

                repo_to_count[normalized_repo_key] = repo_count + 1

            # Resolve commit only when we have a previous commit to compare against.
            commit_sha: str | None = None
            agent_info = AgentInfo(
                uid=uid,
                agent_name=agent_name,
                agent_image=agent_image,
                github_url=raw_github_url,
                normalized_repo=normalized_repo,
                git_commit=None,
            )
            ColoredLogger.info(agent_info.__repr__(), ColoredLogger.GREEN)

            existing = self.agents_dict.get(uid)
            if isinstance(existing, AgentInfo):
                existing_repo = getattr(existing, "normalized_repo", None)
                if not existing_repo:
                    try:
                        existing_repo, _ = normalize_and_validate_github_url(getattr(existing, "github_url", None), miner_uid=uid)
                    except Exception:
                        existing_repo = None

                existing_commit = getattr(existing, "git_commit", None)
                if normalized_repo and existing_commit and existing_repo == normalized_repo:
                    try:
                        if "/commit/" in str(raw_github_url or "") and ref:
                            commit_sha = str(ref)
                        else:
                            commit_sha = resolve_remote_ref_commit(normalized_repo, ref)
                    except Exception:
                        commit_sha = None
                if commit_sha and normalized_repo:
                    commit_url = f"{normalized_repo}/commit/{commit_sha}"
                    try:
                        agent_info.github_url = commit_url
                    except Exception:
                        pass

                # Do not re-evaluate if the submission commit didn't change.
                if normalized_repo and commit_sha and existing_repo == normalized_repo and _commits_match(existing_commit, commit_sha):
                    try:
                        current_season = int(getattr(getattr(self, "season_manager", None), "season_number", 0) or 0)
                    except Exception:
                        current_season = 0
                    last_season = getattr(existing, "last_evaluated_season", None)
                    try:
                        last_season_i = int(last_season) if last_season is not None else None
                    except Exception:
                        last_season_i = None
                    if current_season and last_season_i is not None and last_season_i != int(current_season):
                        # New season → tasks changed, force re-evaluation even if commit unchanged.
                        pass
                    else:
                        # Keep score/evaluated, but allow display metadata to update.
                        try:
                            existing.agent_name = agent_info.agent_name
                            existing.agent_image = agent_info.agent_image
                            existing.github_url = agent_info.github_url
                            if not getattr(existing, "normalized_repo", None):
                                existing.normalized_repo = normalized_repo
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
                    continue

                if not _check_payment_balance(uid):
                    bt.logging.info(f"[collect_commitments] Skipping uid={uid} (changed commit): no remaining paid evals")
                    payment_skip_count += 1
                    continue
                self.agents_queue.put(agent_info)
                new_agents_count += 1
                queued_for_eval_count += 1
                continue

            if not _check_payment_balance(uid):
                bt.logging.info(f"[collect_commitments] Skipping uid={uid} (new miner): no remaining paid evals")
                payment_skip_count += 1
                agent_info.score = 0.0
                agent_info.evaluated = True
                self.agents_dict[uid] = agent_info
                if self.round_manager.round_number == 1:
                    self.agents_on_first_handshake.append(uid)
                continue
            self.agents_dict[uid] = agent_info
            self.agents_queue.put(agent_info)
            if self.round_manager.round_number == 1:
                self.agents_on_first_handshake.append(uid)
            new_agents_count += 1
            queued_for_eval_count += 1

        bt.logging.info(
            "[collect_commitments] complete "
            f"min_stake={min_stake:.4f} "
            f"with_commitment={len(commitment_by_uid)}/{len(candidate_uids)} "
            f"no_commitment={no_commitment_count} "
            f"queued_for_eval={queued_for_eval_count} "
            f"restored_from_pending={restored_from_pending_count} "
            f"missing_fields={missing_field_count} "
            f"invalid_repo={invalid_repo_count} "
            f"repo_cap_skip={repo_cap_skip_count} "
            f"cooldown_skip={cooldown_skip_count} "
            f"unchanged_commit={unchanged_commit_skip_count} "
            f"payment_skip={payment_skip_count} "
            f"new_agents={new_agents_count}"
        )

        # Miners with valid commitments are treated as "active" for IWAP
        # registration and per-round reporting.
        self.active_miner_uids = active_miner_uids_list

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

        blocks_remaining = rm.blocks_until_allowed(current_block)
        seconds_remaining = blocks_remaining * rm.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60
        hours_remaining = minutes_remaining / 60

        current_epoch = rm.block_to_epoch(current_block)
        target_epoch = rm.block_to_epoch(MINIMUM_START_BLOCK)

        eta = f"~{hours_remaining:.1f}h" if hours_remaining >= 1 else f"~{minutes_remaining:.0f}m"
        bt.logging.warning(f"🔒 Locked until block {MINIMUM_START_BLOCK:,} (epoch {target_epoch:.2f}) | now {current_block:,} (epoch {current_epoch:.2f}) | ETA {eta}")

        wait_seconds = min(max(seconds_remaining, 30), 600)
        rm.enter_phase(
            RoundPhase.WAITING,
            block=current_block,
            note=f"Waiting for minimum start block {MINIMUM_START_BLOCK}",
        )
        bt.logging.warning(f"💤 Rechecking in {wait_seconds:.0f}s...")

        await asyncio.sleep(wait_seconds)
        return True
