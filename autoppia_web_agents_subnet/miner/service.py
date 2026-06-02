from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.table import Table

try:
    from async_substrate_interface.errors import StateDiscardedError
except Exception:  # pragma: no cover
    StateDiscardedError = None  # type: ignore[assignment]

from autoppia_web_agents_subnet.validator.config import IPFS_API_URL, MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO
from autoppia_web_agents_subnet.validator.settlement.consensus import (
    _extract_current_run_metrics_from_payload,
    _extract_metrics_from_payload,
    _payload_declares_all_runs_zero,
    _validator_payload_has_positive_best_run_signal,
)
from autoppia_web_agents_subnet.validator.round_start.mixin import _resolve_adaptive_cooldown_rounds
from autoppia_web_agents_subnet.utils.commitments import read_all_plain_commitments
from autoppia_web_agents_subnet.utils.ipfs_client import get_json_async

from .config import get_config_path, load_config
from .ui import (
    console,
    key_value_table,
    make_table,
    print_banner,
    print_info,
    print_success,
    print_warning,
    show_chain_state_panel,
    show_commitment_panel,
    show_panel,
    show_wallet_panel,
)
from .utils import (
    compute_current_round,
    compute_next_round,
    compute_season,
    detect_github_ref_kind,
)

DEFAULT_NETUID = 36
MAX_CHAIN_COMMIT_BYTES = 128
DEFAULT_CONSENSUS_VERSION = 1
DEFAULT_ARCHIVE_CHAIN_ENDPOINT = "wss://archive.chain.opentensor.ai:443"


class MinerCliError(Exception):
    """Raised for user-facing CLI errors."""


class HistoricalCommitmentArchiveRequired(MinerCliError):
    """Raised when historical commitment scanning requires an archive node."""


@dataclass(frozen=True)
class CommonOptions:
    wallet_name: str | None
    wallet_hotkey: str | None
    inspect_hotkey_ss58: str | None
    inspect_round: int | None
    inspect_season: int | None
    consensus_version: int | None
    subtensor_network: str | None
    subtensor_chain_endpoint: str | None
    netuid: int | None


@dataclass(frozen=True)
class ResolvedCommonOptions:
    wallet_name: str
    wallet_hotkey: str
    inspect_hotkey_ss58: str | None
    inspect_round: int | None
    inspect_season: int | None
    consensus_version: int
    subtensor_network: str
    subtensor_chain_endpoint: str | None
    netuid: int


@dataclass(frozen=True)
class LatestConsensusSnapshot:
    source: str
    season: int
    round_number: int
    aggregated_scores: dict[int, float]
    stats_by_miner: dict[int, dict[str, Any]]
    validators: list[dict[str, Any]]
    downloaded_payloads: list[dict[str, Any]]


@dataclass(frozen=True)
class MinerSeasonVersionEntry:
    season: int
    round_number: int
    hotkey: str
    github_url: str | None
    commit_sha: str | None
    normalized_repo: str | None
    reward: float
    score: float
    time_s: float
    cost: float
    penalty: float
    rank: int | None
    tasks_received: int
    tasks_success: int
    source: str


@dataclass(frozen=True)
class ValidatorRoundMinerStatus:
    season: int
    round_number: int
    validator_uid: int | None
    validator_hotkey: str
    present: bool
    reward: float
    evaluated: bool
    miner_score: float
    best_score_in_validator: float
    source: str


def _resolve_subtensor_config(options: ResolvedCommonOptions) -> tuple[str, dict[str, str]]:
    if options.subtensor_chain_endpoint:
        endpoint = options.subtensor_chain_endpoint.strip()
        if endpoint:
            return endpoint, {"network": endpoint}
    return options.subtensor_network, {"network": options.subtensor_network}


def resolve_common_options(options: CommonOptions) -> ResolvedCommonOptions:
    config = load_config()

    wallet_name = (options.wallet_name or config.get("wallet_name") or "default").strip()
    wallet_hotkey = (options.wallet_hotkey or config.get("wallet_hotkey") or "default").strip()
    subtensor_network = (options.subtensor_network or config.get("subtensor_network") or "finney").strip()
    subtensor_chain_endpoint = options.subtensor_chain_endpoint
    if subtensor_chain_endpoint is None:
        configured_endpoint = config.get("subtensor_chain_endpoint")
        if isinstance(configured_endpoint, str) and configured_endpoint.strip():
            subtensor_chain_endpoint = configured_endpoint.strip()
    consensus_version_raw = options.consensus_version if options.consensus_version is not None else config.get("consensus_version", DEFAULT_CONSENSUS_VERSION)
    try:
        consensus_version = int(consensus_version_raw)
    except Exception as exc:
        raise MinerCliError(f"Invalid consensus_version in CLI/config: {consensus_version_raw!r}") from exc
    netuid_raw = options.netuid if options.netuid is not None else config.get("netuid", DEFAULT_NETUID)
    try:
        netuid = int(netuid_raw)
    except Exception as exc:
        raise MinerCliError(f"Invalid netuid in CLI/config: {netuid_raw!r}") from exc

    return ResolvedCommonOptions(
        wallet_name=wallet_name,
        wallet_hotkey=wallet_hotkey,
        inspect_hotkey_ss58=(options.inspect_hotkey_ss58 or "").strip() or None,
        inspect_round=int(options.inspect_round) if options.inspect_round is not None else None,
        inspect_season=int(options.inspect_season) if options.inspect_season is not None else None,
        consensus_version=consensus_version,
        subtensor_network=subtensor_network,
        subtensor_chain_endpoint=subtensor_chain_endpoint,
        netuid=netuid,
    )


def _resolve_target_hotkey_ss58(options: ResolvedCommonOptions, wallet: Any | None) -> str:
    if options.inspect_hotkey_ss58:
        return str(options.inspect_hotkey_ss58).strip()
    if wallet is None:
        raise MinerCliError("No target hotkey available. Pass --hotkey.ss58 or configure a local wallet.")
    return str(wallet.hotkey.ss58_address)


def _validate_submit_inputs(
    github: str,
    agent_name: str,
    agent_image: str,
    target_round: int | None,
    season: int | None,
) -> tuple[str, str, str]:
    from autoppia_web_agents_subnet.opensource.utils_git import normalize_and_validate_github_url

    normalized, ref = normalize_and_validate_github_url(github, require_ref=True)
    if normalized is None or not ref:
        raise MinerCliError(f"Invalid GitHub URL: {github}\n       Must be https://github.com/owner/repo/tree/<ref> or /commit/<sha>.")

    stripped_name = agent_name.strip()
    if not stripped_name:
        raise MinerCliError("--agent.name must not be empty.")

    if season is not None and season <= 0:
        raise MinerCliError("--season must be a positive integer.")

    if target_round is not None and target_round <= 0:
        raise MinerCliError("--target_round must be a positive integer.")

    ref_kind = detect_github_ref_kind(github)
    github_url = f"{normalized}/{ref_kind}/{ref}"
    return github_url, stripped_name, (agent_image or "").strip()


def _build_commitment_payload(*, github_url: str, agent_name: str, agent_image: str, season_number: int, target_round_number: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "t": "m",
        "g": github_url,
        "n": agent_name,
        "r": int(target_round_number),
        "s": int(season_number),
    }
    if agent_image:
        payload["i"] = agent_image
    return payload


def _payload_size_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _fit_commitment_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    fitted = dict(payload)
    warnings: list[str] = []
    if _payload_size_bytes(fitted) <= MAX_CHAIN_COMMIT_BYTES:
        return fitted, warnings
    if fitted.get("i"):
        fitted.pop("i", None)
        warnings.append("Dropped agent image from the on-chain commitment to fit the 128-byte chain limit.")
    if _payload_size_bytes(fitted) <= MAX_CHAIN_COMMIT_BYTES:
        return fitted, warnings
    raise MinerCliError(
        "Commitment payload is too large for the chain metadata limit (128 bytes). "
        "Use a shorter agent name or a shorter GitHub ref, or omit optional fields."
    )


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _cooldown_estimate_for_miner(*, miner_uid: int, current_round: int, aggregated_scores: dict[int, float], stats_by_miner: dict[int, dict[str, Any]]) -> tuple[int, int]:
    best_score = 0.0
    if aggregated_scores:
        best_score = max(_coerce_float(v) for v in aggregated_scores.values())
    stats = stats_by_miner.get(miner_uid) or {}
    miner_score = _coerce_float(stats.get("avg_eval_score"), _coerce_float(aggregated_scores.get(miner_uid)))
    cooldown_rounds = _resolve_adaptive_cooldown_rounds(
        miner_score=miner_score,
        best_score_ever=best_score or 1.0,
        handshake_responded=True,
    )
    next_round = current_round + max(1, cooldown_rounds)
    return cooldown_rounds, next_round


def _normalize_requested_round_for_snapshot(requested_round: int | None) -> int | None:
    """
    Miner CLI round filters should match the round numbers users see in validator
    commitments and local post-consensus snapshots.
    """
    if requested_round is None:
        return None
    return max(1, int(requested_round))


def _target_round_for_status_display(*, inspect_round: int | None, next_round: int) -> int:
    if inspect_round is not None:
        return max(1, int(inspect_round))
    return int(next_round)


def _commitment_target_title(prefix: str, commitment: dict[str, Any] | None) -> str:
    if not isinstance(commitment, dict):
        return f"{prefix} (target unknown)"
    season = _coerce_int(commitment.get("s"), -1)
    round_number = _coerce_int(commitment.get("r"), -1)
    if season > 0 and round_number > 0:
        return f"{prefix} · Season {season} · Round {round_number}"
    if season > 0:
        return f"{prefix} · Season {season}"
    if round_number > 0:
        return f"{prefix} · Round {round_number}"
    return f"{prefix} (target unknown)"


def _is_missing_commitment(commitment: Any) -> bool:
    if commitment is None:
        return True
    if isinstance(commitment, str) and not commitment.strip():
        return True
    return False


def _extract_miner_version_entry(*, season: int, round_number: int, miner: dict[str, Any], source: str) -> MinerSeasonVersionEntry | None:
    if not isinstance(miner, dict):
        return None
    hotkey = str(miner.get("hotkey") or "").strip()
    if not hotkey:
        return None
    run = miner.get("best_run_consensus") if isinstance(miner.get("best_run_consensus"), dict) else {}
    if not run:
        run = miner.get("best_run") if isinstance(miner.get("best_run"), dict) else {}
    github_url = run.get("github_url") or miner.get("github_url")
    commit_sha = run.get("commit_sha")
    normalized_repo = run.get("normalized_repo")
    rank_raw = run.get("rank")
    rank = _coerce_int(rank_raw, -1)
    return MinerSeasonVersionEntry(
        season=int(season),
        round_number=int(round_number),
        hotkey=hotkey,
        github_url=str(github_url).strip() if isinstance(github_url, str) and github_url.strip() else None,
        commit_sha=str(commit_sha).strip() if isinstance(commit_sha, str) and commit_sha.strip() else None,
        normalized_repo=str(normalized_repo).strip() if isinstance(normalized_repo, str) and normalized_repo.strip() else None,
        reward=_coerce_float(run.get("reward")),
        score=_coerce_float(run.get("score")),
        time_s=_coerce_float(run.get("time")),
        cost=_coerce_float(run.get("cost")),
        penalty=_coerce_float(run.get("penalty")),
        rank=(rank if rank > 0 else None),
        tasks_received=_coerce_int(run.get("tasks_received")),
        tasks_success=_coerce_int(run.get("tasks_success")),
        source=source,
    )


def _load_miner_season_history_from_backup_dir(*, target_hotkey_ss58: str, requested_season: int | None = None) -> list[MinerSeasonVersionEntry]:
    backup_dir = (os.getenv("IWAP_BACKUP_DIR") or "").strip()
    if not backup_dir:
        return []

    root = Path(backup_dir)
    if not root.exists():
        return []

    entries: list[MinerSeasonVersionEntry] = []
    for candidate in sorted(root.glob("season_*/round_*/post_consensus.json"), key=lambda path: path.stat().st_mtime):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        season = _coerce_int(payload.get("season"), -1)
        round_number = _coerce_int(payload.get("round"), -1)
        if season <= 0 or round_number <= 0:
            continue
        if requested_season is not None and season != int(requested_season):
            continue
        miners = payload.get("miners") if isinstance(payload.get("miners"), list) else []
        miner = next((item for item in miners if isinstance(item, dict) and str(item.get("hotkey") or "").strip() == target_hotkey_ss58), None)
        entry = _extract_miner_version_entry(season=season, round_number=round_number, miner=miner, source="local-backup")
        if entry is not None:
            entries.append(entry)

    deduped: dict[tuple[int, int], MinerSeasonVersionEntry] = {}
    for entry in entries:
        deduped[(entry.season, entry.round_number)] = entry
    return sorted(deduped.values(), key=lambda item: (item.season, item.round_number))


def _show_miner_season_history(*, entries: list[MinerSeasonVersionEntry], current_commitment: dict[str, Any] | None = None) -> None:
    if not entries:
        return

    latest_key = max((entry.season, entry.round_number) for entry in entries)
    current_commit_round = _coerce_int(current_commitment.get("r"), -1) if isinstance(current_commitment, dict) else -1
    current_commit_season = _coerce_int(current_commitment.get("s"), -1) if isinstance(current_commitment, dict) else -1
    current_commit_github = current_commitment.get("g") if isinstance(current_commitment, dict) else None
    current_commit_name = current_commitment.get("n") if isinstance(current_commitment, dict) else None

    table = make_table(title="Miner Season History", border_style="magenta")
    table.add_column("Round", justify="right")
    table.add_column("Marker")
    table.add_column("GitHub")
    table.add_column("Commit")
    table.add_column("Reward", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Tasks", justify="right")
    table.add_column("Rank", justify="right")
    table.add_column("Source")

    for entry in entries:
        markers: list[str] = []
        if (entry.season, entry.round_number) == latest_key:
            markers.append("latest")
        if entry.season == current_commit_season and entry.round_number == current_commit_round:
            markers.append("current")
        github_text = entry.github_url or "-"
        if entry.season == current_commit_season and entry.round_number == current_commit_round:
            if isinstance(current_commit_github, str) and current_commit_github.strip():
                github_text = current_commit_github.strip()
            if isinstance(current_commit_name, str) and current_commit_name.strip():
                github_text = f"{current_commit_name.strip()} | {github_text}"
        table.add_row(
            str(entry.round_number),
            ", ".join(markers) if markers else "-",
            github_text[:54],
            (entry.commit_sha or "-")[:12],
            f"{entry.reward:.4f}",
            f"{entry.score:.4f}",
            f"{entry.tasks_success}/{entry.tasks_received}",
            str(entry.rank or "-"),
            entry.source,
        )
    console.print(table)


def _extract_validator_round_miner_status(
    *,
    season: int,
    round_number: int,
    validator_uid: int | None,
    validator_hotkey: str,
    payload: dict[str, Any],
    target_hotkey_ss58: str,
    target_miner_uid: int | None = None,
    source: str,
) -> ValidatorRoundMinerStatus | None:
    miners = payload.get("miners") if isinstance(payload.get("miners"), list) else []
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    miner_entry = next((m for m in miners if isinstance(m, dict) and str(m.get("hotkey") or "").strip() == target_hotkey_ss58), None)
    best_score_in_validator = 0.0
    for candidate in miners:
        if not isinstance(candidate, dict):
            continue
        candidate_best = candidate.get("best_run") if isinstance(candidate.get("best_run"), dict) else {}
        best_score_in_validator = max(best_score_in_validator, _coerce_float(candidate_best.get("score")))

    if not isinstance(miner_entry, dict):
        summary_reward = 0.0
        summary_score = 0.0
        if isinstance(summary, dict) and target_miner_uid is not None:
            for key in ("leader_before_round", "leader_after_round", "candidate_this_round"):
                entry = summary.get(key) if isinstance(summary.get(key), dict) else None
                if not isinstance(entry, dict):
                    continue
                if _coerce_int(entry.get("uid"), -1) != int(target_miner_uid):
                    continue
                summary_reward = max(summary_reward, _coerce_float(entry.get("reward")))
                summary_score = max(summary_score, _coerce_float(entry.get("score")))
        if not miners and summary_reward <= 0.0 and summary_score <= 0.0:
            return None
        return ValidatorRoundMinerStatus(
            season=int(season),
            round_number=int(round_number),
            validator_uid=(int(validator_uid) if isinstance(validator_uid, int) else None),
            validator_hotkey=str(validator_hotkey),
            present=summary_reward > 0.0 or summary_score > 0.0,
            reward=summary_reward,
            evaluated=False,
            miner_score=summary_score,
            best_score_in_validator=best_score_in_validator,
            source=source,
        )

    best_run = miner_entry.get("best_run") if isinstance(miner_entry.get("best_run"), dict) else {}
    current_run = miner_entry.get("current_run") if isinstance(miner_entry.get("current_run"), dict) else {}
    best_reward = _coerce_float(best_run.get("reward"))
    current_score = _coerce_float(current_run.get("score"))
    best_score = _coerce_float(best_run.get("score"))
    miner_score = current_score if current_run else best_score

    evaluated = bool(current_run) and _coerce_int(current_run.get("tasks_received")) > 0
    return ValidatorRoundMinerStatus(
        season=int(season),
        round_number=int(round_number),
        validator_uid=(int(validator_uid) if isinstance(validator_uid, int) else None),
        validator_hotkey=str(validator_hotkey),
        present=True,
        reward=best_reward,
        evaluated=evaluated,
        miner_score=miner_score,
        best_score_in_validator=best_score_in_validator,
        source=source,
    )


def _load_validator_round_history_from_backup_dir(*, target_hotkey_ss58: str, requested_season: int | None = None) -> list[ValidatorRoundMinerStatus]:
    backup_dir = (os.getenv("IWAP_BACKUP_DIR") or "").strip()
    if not backup_dir:
        return []

    root = Path(backup_dir)
    if not root.exists():
        return []

    entries: list[ValidatorRoundMinerStatus] = []
    for candidate in sorted(root.glob("season_*/round_*/ipfs_downloaded.json"), key=lambda path: path.stat().st_mtime):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        payloads = payload.get("payloads") if isinstance(payload.get("payloads"), list) else []
        for item in payloads:
            if not isinstance(item, dict):
                continue
            raw = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
            season = _coerce_int((inner or {}).get("s"), -1)
            round_number = _coerce_int((inner or {}).get("r"), -1)
            if season <= 0 or round_number <= 0:
                continue
            if requested_season is not None and season != int(requested_season):
                continue
            entry = _extract_validator_round_miner_status(
                season=season,
                round_number=round_number,
                validator_uid=item.get("validator_uid"),
                validator_hotkey=str(item.get("validator_hotkey") or ""),
                payload=inner if isinstance(inner, dict) else {},
                target_hotkey_ss58=target_hotkey_ss58,
                target_miner_uid=None,
                source="local-backup",
            )
            if entry is not None:
                entries.append(entry)

    deduped: dict[tuple[int, int, str], ValidatorRoundMinerStatus] = {}
    for entry in entries:
        deduped[(entry.season, entry.round_number, entry.validator_hotkey)] = entry
    return sorted(deduped.values(), key=lambda item: (item.season, item.round_number, item.validator_hotkey))


def _validator_history_from_snapshot(*, snapshot: LatestConsensusSnapshot | None, target_hotkey_ss58: str, target_miner_uid: int | None = None) -> list[ValidatorRoundMinerStatus]:
    if snapshot is None:
        return []
    entries: list[ValidatorRoundMinerStatus] = []
    for item in snapshot.downloaded_payloads:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        entry = _extract_validator_round_miner_status(
            season=snapshot.season,
            round_number=snapshot.round_number,
            validator_uid=item.get("uid"),
            validator_hotkey=str(item.get("validator_hotkey") or ""),
            payload=payload,
            target_hotkey_ss58=target_hotkey_ss58,
            target_miner_uid=target_miner_uid,
            source=snapshot.source,
        )
        if entry is not None:
            entries.append(entry)
    return entries


def _extract_round_scan_context(snapshot: LatestConsensusSnapshot | None) -> tuple[int, int, int] | None:
    if snapshot is None:
        return None
    for item in snapshot.downloaded_payloads:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        miners = payload.get("miners") if isinstance(payload.get("miners"), list) else []
        for miner in miners:
            if not isinstance(miner, dict):
                continue
            best_run = miner.get("best_run") if isinstance(miner.get("best_run"), dict) else {}
            evaluation_context = best_run.get("evaluation_context") if isinstance(best_run.get("evaluation_context"), dict) else {}
            minimum_start_block = _coerce_int(evaluation_context.get("minimum_start_block"), -1)
            blocks_per_epoch = _coerce_int(evaluation_context.get("blocks_per_epoch"), -1)
            round_size_epochs = _coerce_float(evaluation_context.get("round_size_epochs"), 0.0)
            round_block_span = int(blocks_per_epoch * round_size_epochs) if blocks_per_epoch > 0 and round_size_epochs > 0 else -1
            if minimum_start_block > 0 and round_block_span > 0:
                return minimum_start_block, round_block_span, int(snapshot.round_number)
    return None


def _round_scan_block_map(*, current_block: int, minimum_start_block: int, round_block_span: int, latest_round_number: int) -> dict[int, int]:
    if current_block <= 0 or minimum_start_block <= 0 or round_block_span <= 0 or latest_round_number <= 0:
        return {}

    latest_round_start_block = minimum_start_block + round_block_span * max(0, latest_round_number - 1)
    latest_round_start_block = min(int(current_block), int(latest_round_start_block))

    blocks: dict[int, int] = {}
    for round_number in range(1, int(latest_round_number) + 1):
        if round_number >= int(latest_round_number):
            block = int(current_block)
        else:
            rounds_back = int(latest_round_number) - int(round_number) - 1
            start_of_next_round = latest_round_start_block - round_block_span * max(0, rounds_back)
            block = max(minimum_start_block, int(start_of_next_round) - 1)
        blocks[int(round_number)] = int(block)
    return blocks


async def _validator_history_from_chain_scan(
    *,
    st,
    netuid: int,
    current_block: int,
    snapshot: LatestConsensusSnapshot | None,
    target_hotkey_ss58: str,
    target_miner_uid: int | None = None,
    consensus_version: int,
    source_label: str = "chain-scan",
) -> list[ValidatorRoundMinerStatus]:
    if snapshot is None:
        return []
    scan_context = _extract_round_scan_context(snapshot)
    if scan_context is None:
        return []
    minimum_start_block, round_block_span, max_round = scan_context
    validator_rows = snapshot.validators if isinstance(snapshot.validators, list) else []
    if not validator_rows or max_round <= 1:
        return []
    round_blocks = _round_scan_block_map(
        current_block=int(current_block),
        minimum_start_block=int(minimum_start_block),
        round_block_span=int(round_block_span),
        latest_round_number=int(max_round),
    )
    if not round_blocks:
        return []

    payload_cache: dict[str, dict[str, Any] | None] = {}
    entries: list[ValidatorRoundMinerStatus] = []
    validator_row_by_hotkey = {
        str(row.get("hotkey") or "").strip(): row
        for row in validator_rows
        if isinstance(row, dict) and str(row.get("hotkey") or "").strip()
    }

    for round_number in range(1, int(max_round) + 1):
        block = round_blocks.get(int(round_number))
        if block is None:
            continue
        try:
            commitments_at_block = await read_all_plain_commitments(st, netuid=netuid, block=block)
        except Exception as exc:
            if StateDiscardedError is not None and isinstance(exc, StateDiscardedError):
                raise HistoricalCommitmentArchiveRequired(
                    "Historical commitment scan needs an archive node for older blocks."
                ) from exc
            continue
        for validator_hotkey, row in validator_row_by_hotkey.items():
            commitment = commitments_at_block.get(validator_hotkey)
            if not isinstance(commitment, dict):
                continue
            try:
                version = int(commitment.get("v", consensus_version))
                season = int(commitment.get("s"))
                committed_round = int(commitment.get("r"))
            except Exception:
                continue
            cid = commitment.get("c")
            if version != int(consensus_version) or season != int(snapshot.season) or committed_round != int(round_number):
                continue
            if not isinstance(cid, str) or not cid.strip():
                continue
            payload = payload_cache.get(cid)
            if payload is None and cid not in payload_cache:
                try:
                    payload, _norm, _sha = await get_json_async(cid.strip(), api_url=IPFS_API_URL)
                except Exception:
                    payload = None
                payload_cache[cid] = payload if isinstance(payload, dict) else None
            payload = payload_cache.get(cid)
            if not isinstance(payload, dict):
                continue
            entry = _extract_validator_round_miner_status(
                season=int(snapshot.season),
                round_number=int(round_number),
                validator_uid=row.get("uid"),
                validator_hotkey=validator_hotkey,
                payload=payload,
                target_hotkey_ss58=target_hotkey_ss58,
                target_miner_uid=target_miner_uid,
                source=source_label,
            )
            if entry is not None:
                entries.append(entry)

    deduped: dict[tuple[int, int, str], ValidatorRoundMinerStatus] = {}
    for entry in entries:
        deduped[(entry.season, entry.round_number, entry.validator_hotkey)] = entry
    return sorted(deduped.values(), key=lambda item: (item.season, item.round_number, item.validator_hotkey))


def _show_validator_round_matrix(*, entries: list[ValidatorRoundMinerStatus], title: str, value_getter) -> None:
    if not entries:
        return
    rounds = sorted({entry.round_number for entry in entries})
    validators = sorted({(entry.validator_hotkey, entry.validator_uid) for entry in entries}, key=lambda item: (item[1] is None, item[1], item[0]))
    entry_map = {(entry.validator_hotkey, entry.round_number): entry for entry in entries}

    table = make_table(title=title, border_style="cyan")
    table.add_column("Validator")
    for round_number in rounds:
        table.add_column(f"R{round_number}", justify="right")

    for validator_hotkey, validator_uid in validators:
        label = f"{validator_uid if validator_uid is not None else '?'}:{validator_hotkey[:10]}"
        row = [label]
        for round_number in rounds:
            entry = entry_map.get((validator_hotkey, round_number))
            row.append(value_getter(entry))
        table.add_row(*row)
    console.print(table)


def _show_validator_cooldown_table(*, entries: list[ValidatorRoundMinerStatus]) -> None:
    if not entries:
        return

    latest_round = max(entry.round_number for entry in entries)
    by_validator: dict[str, list[ValidatorRoundMinerStatus]] = {}
    validator_uid_map: dict[str, int | None] = {}
    for entry in entries:
        by_validator.setdefault(entry.validator_hotkey, []).append(entry)
        validator_uid_map[entry.validator_hotkey] = entry.validator_uid

    table = make_table(title="Validator Cooldown", border_style="yellow")
    table.add_column("Validator")
    table.add_column("Cooldown", justify="right")

    for validator_hotkey in sorted(by_validator, key=lambda hk: (validator_uid_map.get(hk) is None, validator_uid_map.get(hk), hk)):
        validator_entries = sorted(by_validator[validator_hotkey], key=lambda item: item.round_number)
        latest_eval = next((entry for entry in reversed(validator_entries) if entry.evaluated), None)
        remaining = 0
        if latest_eval is not None:
            cooldown_rounds = _resolve_adaptive_cooldown_rounds(
                miner_score=latest_eval.miner_score,
                best_score_ever=max(latest_eval.best_score_in_validator, 1.0e-9),
                handshake_responded=True,
            )
            rounds_elapsed = max(0, latest_round - latest_eval.round_number)
            remaining = max(0, int(cooldown_rounds) - rounds_elapsed)
        label = f"{validator_uid_map.get(validator_hotkey) if validator_uid_map.get(validator_hotkey) is not None else '?'}:{validator_hotkey[:10]}"
        table.add_row(label, str(remaining))
    console.print(table)


def _show_consensus_summary(*, miner_uid: int, current_round: int, aggregated_scores: dict[int, float], details: dict[str, Any]) -> None:
    stats_by_miner = details.get("stats_by_miner") if isinstance(details.get("stats_by_miner"), dict) else {}
    validators = details.get("validators") if isinstance(details.get("validators"), list) else []
    downloaded_payloads = details.get("downloaded_payloads") if isinstance(details.get("downloaded_payloads"), list) else []

    if miner_uid not in aggregated_scores:
        print_warning("Miner is not listed in payload.miners for this latest validator payload. Tables below may still show season-leader signals from validator summaries.")
        return

    ranking = sorted(aggregated_scores.items(), key=lambda item: item[1], reverse=True)
    rank = next((idx for idx, (uid, _score) in enumerate(ranking, start=1) if int(uid) == int(miner_uid)), None)
    miner_stats = stats_by_miner.get(miner_uid) if isinstance(stats_by_miner, dict) else {}
    cooldown_rounds, next_round = _cooldown_estimate_for_miner(
        miner_uid=miner_uid,
        current_round=current_round,
        aggregated_scores=aggregated_scores,
        stats_by_miner=stats_by_miner,
    )

    summary = Table(show_header=False, border_style="dim", pad_edge=False, box=None)
    summary.add_column("Field", style="bold")
    summary.add_column("Value")
    summary.add_row("Validators in consensus", str(len(validators)))
    summary.add_row("Latest consensus rank", str(rank or "-"))
    summary.add_row("Consensus reward", f"{_coerce_float(aggregated_scores.get(miner_uid)):.4f}")
    summary.add_row("Avg score", f"{_coerce_float(miner_stats.get('avg_eval_score')):.4f}")
    summary.add_row("Avg time", f"{_coerce_float(miner_stats.get('avg_eval_time')):.2f}s")
    summary.add_row("Avg cost", f"${_coerce_float(miner_stats.get('avg_cost')):.4f}")
    summary.add_row("Avg penalty", f"{_coerce_float(miner_stats.get('avg_penalty')):.4f}")
    summary.add_row("Tasks success", f"{_coerce_int(miner_stats.get('tasks_success'))}/{_coerce_int(miner_stats.get('tasks_sent'))}")
    summary.add_row("Estimated cooldown", f"{cooldown_rounds} round(s)")
    summary.add_row("Estimated next eval", f"round {next_round}")
    show_panel(summary, title="Latest Payload Consensus View", border_style="green")

    top_table = make_table(title="Top Consensus Ranking", border_style="green")
    top_table.add_column("Rank", justify="right")
    top_table.add_column("UID", justify="right")
    top_table.add_column("Reward", justify="right")
    top_table.add_column("Score", justify="right")
    top_table.add_column("Time", justify="right")
    top_table.add_column("Cost", justify="right")
    top_table.add_column("Penalty", justify="right")
    top_table.add_column("Tasks", justify="right")
    for idx, (uid, reward) in enumerate(ranking[:10], start=1):
        stats = stats_by_miner.get(int(uid), {}) if isinstance(stats_by_miner, dict) else {}
        top_table.add_row(
            str(idx),
            str(uid),
            f"{_coerce_float(reward):.4f}",
            f"{_coerce_float(stats.get('avg_eval_score')):.4f}",
            f"{_coerce_float(stats.get('avg_eval_time')):.2f}s",
            f"${_coerce_float(stats.get('avg_cost')):.4f}",
            f"{_coerce_float(stats.get('avg_penalty')):.4f}",
            f"{_coerce_int(stats.get('tasks_success'))}/{_coerce_int(stats.get('tasks_sent'))}",
        )
    console.print(top_table)

    validator_table = make_table(title="Validator Commitments Used", border_style="cyan")
    validator_table.add_column("UID", justify="right")
    validator_table.add_column("Hotkey")
    validator_table.add_column("Stake", justify="right")
    validator_table.add_column("CID")
    for row in validators:
        if not isinstance(row, dict):
            continue
        validator_table.add_row(
            str(row.get("uid", "?")),
            str(row.get("hotkey", ""))[:18],
            f"{_coerce_float(row.get('stake')):.2f}",
            str(row.get("cid", ""))[:18],
        )
    console.print(validator_table)

    payload_table = make_table(title="Per-Validator View For This Miner", border_style="blue")
    payload_table.add_column("Validator UID", justify="right")
    payload_table.add_column("Validator")
    payload_table.add_column("Local Reward", justify="right")
    payload_table.add_column("Local Score", justify="right")
    payload_table.add_column("Tasks", justify="right")
    payload_table.add_column("GitHub")
    for entry in downloaded_payloads:
        if not isinstance(entry, dict):
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        miners = payload.get("miners") if isinstance(payload.get("miners"), list) else []
        miner_entry = next((m for m in miners if isinstance(m, dict) and _coerce_int(m.get("uid"), -1) == miner_uid), None)
        if not isinstance(miner_entry, dict):
            continue
        best_run = miner_entry.get("best_run") if isinstance(miner_entry.get("best_run"), dict) else {}
        payload_table.add_row(
            str(entry.get("uid", "?")),
            str(entry.get("validator_hotkey", ""))[:18],
            f"{_coerce_float(best_run.get('reward')):.4f}",
            f"{_coerce_float(best_run.get('score')):.4f}",
            f"{_coerce_int(best_run.get('tasks_success'))}/{_coerce_int(best_run.get('tasks_received'))}",
            str(best_run.get("github_url") or miner_entry.get("github_url") or "-")[:50],
        )
    if payload_table.row_count:
        console.print(payload_table)


def _weighted_metric_average(metric_acc: dict[int, dict[str, float]], weight_total: dict[int, float], uid: int, key: str) -> float:
    total_weight = float(weight_total.get(uid, 0.0) or 0.0)
    if total_weight <= 0.0:
        return 0.0
    return float((metric_acc.get(uid) or {}).get(key, 0.0)) / total_weight


def _rank_candidate_season_round_pairs(rows: list[dict[str, Any]]) -> list[tuple[int, int]]:
    pair_weights: dict[tuple[int, int], float] = {}
    for row in rows:
        try:
            pair = (int(row["season"]), int(row["round_number"]))
        except Exception:
            continue
        pair_weights[pair] = pair_weights.get(pair, 0.0) + _coerce_float(row.get("stake"), 0.0)
    ranked = sorted(pair_weights.items(), key=lambda item: (item[1], item[0][0], item[0][1]), reverse=True)
    return [pair for pair, _weight in ranked]


async def _load_latest_consensus_snapshot(
    *,
    st,
    netuid: int,
    metagraph: Any,
    consensus_version: int,
    requested_round: int | None = None,
    requested_season: int | None = None,
    target_miner_uid: int | None = None,
) -> LatestConsensusSnapshot | None:
    all_commitments = await read_all_plain_commitments(st, netuid=netuid)
    try:
        hotkeys = list(getattr(metagraph, "hotkeys", []))
    except Exception:
        hotkeys = []
    try:
        stakes = list(getattr(metagraph, "stake", []))
    except Exception:
        stakes = []
    hotkey_to_uid = {str(hk).strip(): idx for idx, hk in enumerate(hotkeys) if hk}

    validator_rows: list[dict[str, Any]] = []
    for hotkey, entry in (all_commitments or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("t") == "m":
            continue
        cid = entry.get("c")
        if not isinstance(cid, str) or not cid.strip():
            continue
        try:
            season = int(entry.get("s"))
            round_number = int(entry.get("r"))
            version = int(entry.get("v", consensus_version))
        except Exception:
            continue
        if version != int(consensus_version):
            continue
        uid = hotkey_to_uid.get(str(hotkey).strip())
        if uid is None:
            with contextlib.suppress(Exception):
                uid = await st.get_uid_for_hotkey_on_subnet(str(hotkey).strip(), netuid)
        stake = _coerce_float(stakes[uid] if isinstance(uid, int) and uid < len(stakes) else 1.0)
        if stake < float(MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO):
            continue
        validator_rows.append(
            {
                "hotkey": str(hotkey).strip(),
                "uid": int(uid) if isinstance(uid, int) else -1,
                "stake": stake,
                "cid": cid.strip(),
                "season": season,
                "round_number": round_number,
            }
        )

    if not validator_rows:
        return None

    async def _fetch_compatible_payloads(rows: list[dict[str, Any]], *, season: int, round_number: int) -> list[dict[str, Any]]:
        compatible_payloads: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload, _norm, _sha = await get_json_async(row["cid"], api_url=IPFS_API_URL)
            except Exception as exc:
                print_warning(f"Skipping validator UID {row['uid']} CID {row['cid'][:18]}: {type(exc).__name__}")
                continue
            if not isinstance(payload, dict):
                continue
            if _coerce_int(payload.get("s"), -1) != int(season) or _coerce_int(payload.get("r"), -1) != int(round_number):
                continue
            rewards, miner_metrics = _extract_metrics_from_payload(payload)
            current_run_metrics = _extract_current_run_metrics_from_payload(payload)
            if not rewards:
                continue
            compatible_payloads.append(
                {
                    "hotkey": row["hotkey"],
                    "uid": row["uid"],
                    "stake": row["stake"],
                    "cid": row["cid"],
                    "payload": payload,
                    "rewards": rewards,
                    "miner_metrics": miner_metrics,
                    "current_run_metrics": current_run_metrics,
                    "declares_all_zero": _payload_declares_all_runs_zero(payload, rewards),
                }
            )
        return compatible_payloads

    if requested_round is not None:
        if requested_season is None:
            candidate_pairs = _rank_candidate_season_round_pairs(
                [row for row in validator_rows if int(row["round_number"]) == int(requested_round)]
            )
            if not candidate_pairs:
                return None
        else:
            candidate_pairs = [(int(requested_season), int(requested_round))]
    else:
        candidate_pairs = _rank_candidate_season_round_pairs(validator_rows)

    selected_season: int | None = None
    selected_round: int | None = None
    compatible_payloads: list[dict[str, Any]] = []

    for season_candidate, round_candidate in candidate_pairs:
        selected_rows = [
            row
            for row in validator_rows
            if int(row["season"]) == int(season_candidate) and int(row["round_number"]) == int(round_candidate)
        ]
        if not selected_rows:
            continue
        candidate_payloads = await _fetch_compatible_payloads(
            selected_rows,
            season=season_candidate,
            round_number=round_candidate,
        )
        if not candidate_payloads:
            continue
        if target_miner_uid is not None and requested_season is None and requested_round is not None:
            miner_present = any(int(target_miner_uid) in entry["rewards"] for entry in candidate_payloads)
            if not miner_present:
                continue
        selected_season = int(season_candidate)
        selected_round = int(round_candidate)
        compatible_payloads = candidate_payloads
        break

    if selected_season is None or selected_round is None or not compatible_payloads:
        return None

    has_positive_best_run_signal = any(_validator_payload_has_positive_best_run_signal(entry["rewards"]) for entry in compatible_payloads)
    filtered_payloads = [
        entry
        for entry in compatible_payloads
        if not (has_positive_best_run_signal and bool(entry.get("declares_all_zero")))
    ]
    if not filtered_payloads:
        filtered_payloads = compatible_payloads

    weighted_sum: dict[int, float] = {}
    weight_total: dict[int, float] = {}
    metric_acc: dict[int, dict[str, float]] = {}
    downloaded_payloads: list[dict[str, Any]] = []
    validators: list[dict[str, Any]] = []

    metric_keys = ("avg_reward", "avg_eval_score", "avg_eval_time", "avg_cost", "avg_penalty", "tasks_sent", "tasks_success")

    for entry in filtered_payloads:
        effective_weight = float(entry["stake"]) if float(entry["stake"]) > 0.0 else 1.0
        rewards = entry["rewards"]
        miner_metrics = entry["miner_metrics"]
        for uid, reward in rewards.items():
            weighted_sum[uid] = weighted_sum.get(uid, 0.0) + effective_weight * float(reward)
            weight_total[uid] = weight_total.get(uid, 0.0) + effective_weight

        for uid, metrics in miner_metrics.items():
            bucket = metric_acc.setdefault(uid, {})
            for key in metric_keys:
                value = _coerce_float(metrics.get(key))
                bucket[key] = bucket.get(key, 0.0) + effective_weight * value

        validators.append(
            {
                "uid": int(entry["uid"]),
                "hotkey": str(entry["hotkey"]),
                "stake": float(entry["stake"]),
                "cid": str(entry["cid"]),
            }
        )
        downloaded_payloads.append(
            {
                "uid": int(entry["uid"]),
                "validator_hotkey": str(entry["hotkey"]),
                "cid": str(entry["cid"]),
                "payload": entry["payload"],
            }
        )

    aggregated_scores = {
        uid: (float(weighted_sum[uid]) / float(weight_total[uid]))
        for uid in weighted_sum
        if float(weight_total.get(uid, 0.0)) > 0.0
    }
    stats_by_miner = {
        uid: {
            "avg_reward": _weighted_metric_average(metric_acc, weight_total, uid, "avg_reward"),
            "avg_eval_score": _weighted_metric_average(metric_acc, weight_total, uid, "avg_eval_score"),
            "avg_eval_time": _weighted_metric_average(metric_acc, weight_total, uid, "avg_eval_time"),
            "avg_cost": _weighted_metric_average(metric_acc, weight_total, uid, "avg_cost"),
            "avg_penalty": _weighted_metric_average(metric_acc, weight_total, uid, "avg_penalty"),
            "tasks_sent": int(round(_weighted_metric_average(metric_acc, weight_total, uid, "tasks_sent"))),
            "tasks_success": int(round(_weighted_metric_average(metric_acc, weight_total, uid, "tasks_success"))),
        }
        for uid in aggregated_scores
    }
    return LatestConsensusSnapshot(
        source="chain",
        season=int(selected_season),
        round_number=int(selected_round),
        aggregated_scores=aggregated_scores,
        stats_by_miner=stats_by_miner,
        validators=validators,
        downloaded_payloads=downloaded_payloads,
    )


def _snapshot_from_post_consensus(post: dict[str, Any]) -> LatestConsensusSnapshot | None:
    miners = post.get("miners")
    if not isinstance(miners, list) or not miners:
        return None

    aggregated_scores: dict[int, float] = {}
    stats_by_miner: dict[int, dict[str, Any]] = {}
    for miner in miners:
        if not isinstance(miner, dict):
            continue
        uid = _coerce_int(miner.get("uid"), -1)
        if uid < 0:
            continue
        run = miner.get("best_run_consensus") if isinstance(miner.get("best_run_consensus"), dict) else {}
        if not run:
            run = miner.get("best_run") if isinstance(miner.get("best_run"), dict) else {}
        aggregated_scores[uid] = _coerce_float(run.get("reward"))
        stats_by_miner[uid] = {
            "avg_reward": _coerce_float(run.get("reward")),
            "avg_eval_score": _coerce_float(run.get("score")),
            "avg_eval_time": _coerce_float(run.get("time")),
            "avg_cost": _coerce_float(run.get("cost")),
            "avg_penalty": _coerce_float(run.get("penalty")),
            "tasks_sent": _coerce_int(run.get("tasks_received")),
            "tasks_success": _coerce_int(run.get("tasks_success")),
        }

    if not aggregated_scores:
        return None

    return LatestConsensusSnapshot(
        source="local-backup",
        season=_coerce_int(post.get("season")),
        round_number=_coerce_int(post.get("round")),
        aggregated_scores=aggregated_scores,
        stats_by_miner=stats_by_miner,
        validators=[],
        downloaded_payloads=[],
    )


def _load_latest_local_snapshot_from_backup_dir(*, requested_round: int | None = None, requested_season: int | None = None) -> LatestConsensusSnapshot | None:
    backup_dir = (os.getenv("IWAP_BACKUP_DIR") or "").strip()
    if not backup_dir:
        return None

    root = Path(backup_dir)
    if not root.exists():
        return None

    candidates = sorted(root.glob("season_*/round_*/post_consensus.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        snapshot = _snapshot_from_post_consensus(payload)
        if snapshot is None:
            continue
        if requested_round is not None and int(snapshot.round_number) != int(requested_round):
            continue
        if requested_season is not None and int(snapshot.season) != int(requested_season):
            continue
        if snapshot is not None:
            return snapshot
    return None


async def run_submit(
    *,
    options: CommonOptions,
    github: str,
    agent_name: str,
    agent_image: str,
    target_round: int | None,
    season: int | None,
) -> None:
    import bittensor as bt

    from autoppia_web_agents_subnet.utils.commitments import read_my_plain_json, write_plain_commitment_json

    print_banner()
    options = resolve_common_options(options)
    github_url, stripped_name, stripped_image = _validate_submit_inputs(github, agent_name, agent_image, target_round, season)

    wallet = bt.Wallet(name=options.wallet_name, hotkey=options.wallet_hotkey)
    network_label, subtensor_kwargs = _resolve_subtensor_config(options)
    show_wallet_panel(wallet, network_label, options.netuid)

    async with bt.AsyncSubtensor(**subtensor_kwargs) as st:
        with console.status("[bold cyan]Connecting to subtensor...", spinner="dots"):
            current_block = await st.get_current_block()

        season_number = season if season is not None else compute_season(current_block)
        target_round_number = target_round if target_round is not None else compute_next_round(current_block, season_number)
        current_round = compute_current_round(current_block, season_number)

        show_chain_state_panel(current_block, season_number, current_round, target_round_number)
        payload, payload_warnings = _fit_commitment_payload(_build_commitment_payload(
            github_url=github_url,
            agent_name=stripped_name,
            agent_image=stripped_image,
            season_number=season_number,
            target_round_number=target_round_number,
        ))
        show_commitment_panel(payload, title="Commitment Payload", border_style="blue")
        for warning in payload_warnings:
            print_warning(warning)

        with console.status("[bold cyan]Submitting commitment on-chain...", spinner="dots"):
            ok = await write_plain_commitment_json(st, wallet=wallet, data=payload, netuid=options.netuid)
        if not ok:
            raise MinerCliError("Commitment submission failed.")
        print_success(f"Commitment submitted for season {season_number}, round {target_round_number}.")

        with console.status("[bold cyan]Verifying on-chain commitment...", spinner="dots"):
            readback = await read_my_plain_json(st, wallet=wallet, netuid=options.netuid)
        if readback:
            show_commitment_panel(readback, title="On-Chain Verification", border_style="green")
        else:
            print_warning("Could not read back commitment (may take a block to propagate).")


async def run_show(*, options: CommonOptions) -> None:
    import bittensor as bt

    from autoppia_web_agents_subnet.utils.commitments import read_my_plain_json, read_plain_commitment

    print_banner()
    options = resolve_common_options(options)
    normalized_inspect_round = _normalize_requested_round_for_snapshot(options.inspect_round)
    network_label, subtensor_kwargs = _resolve_subtensor_config(options)
    wallet = None if options.inspect_hotkey_ss58 else bt.Wallet(name=options.wallet_name, hotkey=options.wallet_hotkey)
    if wallet is not None:
        show_wallet_panel(wallet, network_label, options.netuid)
    else:
        show_panel(
            key_value_table(
                [
                    ("Hotkey", options.inspect_hotkey_ss58),
                    ("Network", network_label),
                    ("Netuid", options.netuid),
                ]
            ),
            title="Target Hotkey",
            border_style="blue",
        )

    async with bt.AsyncSubtensor(**subtensor_kwargs) as st:
        with console.status("[bold cyan]Connecting to subtensor...", spinner="dots"):
            current_block = await st.get_current_block()
        season_number = compute_season(current_block)
        current_round = compute_current_round(current_block, season_number)
        show_chain_state_panel(current_block, season_number, current_round)
        with console.status("[bold cyan]Reading commitment...", spinner="dots"):
            if wallet is not None:
                commitment = await read_my_plain_json(st, wallet=wallet, netuid=options.netuid)
            else:
                commitment = await read_plain_commitment(st, hotkey_ss58=_resolve_target_hotkey_ss58(options, wallet), netuid=options.netuid)
        if _is_missing_commitment(commitment):
            print_warning(f"No commitment found on-chain for hotkey {_resolve_target_hotkey_ss58(options, wallet)}.")
        elif not isinstance(commitment, dict):
            show_panel(
                key_value_table([("Raw commitment", commitment)]),
                title="On-Chain Commitment (target unknown)",
                border_style="green",
            )
        else:
            show_commitment_panel(
                commitment,
                title=_commitment_target_title("On-Chain Commitment", commitment),
                border_style="green",
            )
            if normalized_inspect_round is not None and _coerce_int(commitment.get("r"), -1) != int(normalized_inspect_round):
                print_warning(
                    f"Current commitment targets internal round {_coerce_int(commitment.get('r'), -1)}, not requested UI round {int(options.inspect_round)} (internal {int(normalized_inspect_round)})."
                )
            if options.inspect_season is not None and _coerce_int(commitment.get("s"), -1) != int(options.inspect_season):
                print_warning(
                    f"Current commitment targets season {_coerce_int(commitment.get('s'), -1)}, not requested season {int(options.inspect_season)}."
                )

        target_hotkey_ss58 = _resolve_target_hotkey_ss58(options, wallet)
        history_season = options.inspect_season
        if history_season is None and isinstance(commitment, dict):
            commit_season = _coerce_int(commitment.get("s"), -1)
            if commit_season > 0:
                history_season = commit_season
        history_entries = _load_miner_season_history_from_backup_dir(
            target_hotkey_ss58=target_hotkey_ss58,
            requested_season=history_season,
        )
        if history_entries and history_season is None:
            latest_entry = history_entries[-1]
            history_entries = _load_miner_season_history_from_backup_dir(
                target_hotkey_ss58=target_hotkey_ss58,
                requested_season=latest_entry.season,
            )
        if history_entries:
            _show_miner_season_history(entries=history_entries, current_commitment=commitment if isinstance(commitment, dict) else None)
        elif (os.getenv("IWAP_BACKUP_DIR") or "").strip():
            print_info("No miner season history found in IWAP_BACKUP_DIR for this hotkey.")


async def run_status(*, options: CommonOptions) -> None:
    import bittensor as bt

    from autoppia_web_agents_subnet.utils.commitments import read_my_plain_json, read_plain_commitment

    print_banner()
    options = resolve_common_options(options)
    normalized_inspect_round = _normalize_requested_round_for_snapshot(options.inspect_round)
    network_label, subtensor_kwargs = _resolve_subtensor_config(options)
    wallet = None if options.inspect_hotkey_ss58 else bt.Wallet(name=options.wallet_name, hotkey=options.wallet_hotkey)
    target_hotkey_ss58 = _resolve_target_hotkey_ss58(options, wallet)
    if wallet is not None:
        show_wallet_panel(wallet, network_label, options.netuid)
    else:
        show_panel(
            key_value_table(
                [
                    ("Hotkey", target_hotkey_ss58),
                    ("Network", network_label),
                    ("Netuid", options.netuid),
                ]
            ),
            title="Target Hotkey",
            border_style="blue",
        )

    async with bt.AsyncSubtensor(**subtensor_kwargs) as st:
        with console.status("[bold cyan]Connecting to subtensor...", spinner="dots"):
            current_block = await st.get_current_block()
            metagraph = await st.metagraph(options.netuid)
            miner_uid = await st.get_uid_for_hotkey_on_subnet(target_hotkey_ss58, options.netuid)
        if miner_uid is None:
            raise MinerCliError(f"Hotkey {target_hotkey_ss58} is not registered on netuid {options.netuid}.")

        season_number = compute_season(current_block)
        current_round = compute_current_round(current_block, season_number)
        next_round = compute_next_round(current_block, season_number)
        show_chain_state_panel(
            current_block,
            season_number,
            current_round,
            _target_round_for_status_display(inspect_round=options.inspect_round, next_round=next_round),
        )
        print_info(f"Using consensus version {options.consensus_version}.")

        with console.status("[bold cyan]Reading your current commitment...", spinner="dots"):
            if wallet is not None:
                commitment = await read_my_plain_json(st, wallet=wallet, netuid=options.netuid)
            else:
                commitment = await read_plain_commitment(st, hotkey_ss58=target_hotkey_ss58, netuid=options.netuid)
        if _is_missing_commitment(commitment):
            print_warning(f"No current commitment found for hotkey {target_hotkey_ss58}.")
        elif not isinstance(commitment, dict):
            show_panel(
                key_value_table([("Raw commitment", commitment)]),
                title="Current Commitment (target unknown)",
                border_style="green",
            )
        else:
            show_commitment_panel(
                commitment,
                title=_commitment_target_title("Current Commitment", commitment),
                border_style="green",
            )

        with console.status("[bold cyan]Scanning validator commitments for the latest consensus snapshot...", spinner="dots"):
            snapshot = await _load_latest_consensus_snapshot(
                st=st,
                netuid=options.netuid,
                metagraph=metagraph,
                consensus_version=options.consensus_version,
                requested_round=normalized_inspect_round,
                requested_season=options.inspect_season,
                target_miner_uid=int(miner_uid),
            )
        if snapshot is None:
            snapshot = _load_latest_local_snapshot_from_backup_dir(
                requested_round=normalized_inspect_round,
                requested_season=options.inspect_season,
            )
        if snapshot is None:
            if options.inspect_round is not None:
                round_msg = f" for round {int(options.inspect_round)}"
                if options.inspect_season is not None:
                    round_msg += f" season {int(options.inspect_season)}"
            else:
                round_msg = ""
            print_warning(f"No compatible validator consensus snapshot found on-chain or in IWAP_BACKUP_DIR{round_msg}.")
            return

        snapshot_table = key_value_table(
            [
                ("Payload source", snapshot.source),
                ("Consensus version", options.consensus_version),
                ("Payload season", snapshot.season),
                ("Payload round", snapshot.round_number),
                ("Requested UI round", int(options.inspect_round) if options.inspect_round is not None else "-"),
                ("Validators used", len(snapshot.validators)),
                ("Payload meaning", "latest validator commitment, not full historical season data"),
                ("Config path", get_config_path()),
            ]
        )
        show_panel(snapshot_table, title="Latest Validator Payload", border_style="green")
        _show_consensus_summary(
            miner_uid=int(miner_uid),
            current_round=int(snapshot.round_number),
            aggregated_scores=snapshot.aggregated_scores,
            details={
                "stats_by_miner": snapshot.stats_by_miner,
                "validators": snapshot.validators,
                "downloaded_payloads": snapshot.downloaded_payloads,
            },
        )

        with console.status("[bold cyan]Loading historical validator commitments for this miner...", spinner="dots"):
            validator_history = _load_validator_round_history_from_backup_dir(
                target_hotkey_ss58=target_hotkey_ss58,
                requested_season=snapshot.season,
            )
            if not validator_history:
                try:
                    validator_history = await _validator_history_from_chain_scan(
                        st=st,
                        netuid=options.netuid,
                        current_block=int(current_block),
                        snapshot=snapshot,
                        target_hotkey_ss58=target_hotkey_ss58,
                        target_miner_uid=int(miner_uid),
                        consensus_version=options.consensus_version,
                        source_label="chain-scan",
                    )
                except HistoricalCommitmentArchiveRequired:
                    print_info(f"Historical commitment scan requires an archive node. Retrying via {DEFAULT_ARCHIVE_CHAIN_ENDPOINT}.")
                    with console.status("[bold cyan]Scanning historical commitments via archive node...", spinner="dots"):
                        async with bt.AsyncSubtensor(network=DEFAULT_ARCHIVE_CHAIN_ENDPOINT) as archive_st:
                            validator_history = await _validator_history_from_chain_scan(
                                st=archive_st,
                                netuid=options.netuid,
                                current_block=int(current_block),
                                snapshot=snapshot,
                                target_hotkey_ss58=target_hotkey_ss58,
                                target_miner_uid=int(miner_uid),
                                consensus_version=options.consensus_version,
                                source_label="archive-chain-scan",
                            )
        if not validator_history:
            validator_history = _validator_history_from_snapshot(
                snapshot=snapshot,
                target_hotkey_ss58=target_hotkey_ss58,
                target_miner_uid=int(miner_uid),
            )

        if validator_history:
            _show_validator_round_matrix(
                entries=validator_history,
                title="Validator Reward Signal By Round",
                value_getter=lambda entry: (f"{entry.reward:.4f}" if entry is not None and entry.present else ""),
            )
            _show_validator_round_matrix(
                entries=validator_history,
                title="Validator Evaluation Signal By Round",
                value_getter=lambda entry: ("X" if entry is not None and entry.evaluated else ""),
            )
            _show_validator_cooldown_table(entries=validator_history)
        elif (os.getenv("IWAP_BACKUP_DIR") or "").strip():
            print_info("No per-validator round history found in IWAP_BACKUP_DIR for this miner.")


def render_config_panel() -> None:
    config = load_config()
    rows = [
        ("Config path", get_config_path()),
        ("wallet_name", config.get("wallet_name", "default")),
        ("wallet_hotkey", config.get("wallet_hotkey", "default")),
        ("subtensor_network", config.get("subtensor_network", "finney")),
        ("subtensor_chain_endpoint", config.get("subtensor_chain_endpoint", "")),
        ("netuid", config.get("netuid", DEFAULT_NETUID)),
        ("consensus_version", config.get("consensus_version", DEFAULT_CONSENSUS_VERSION)),
        ("github", config.get("github", "")),
        ("agent_name", config.get("agent_name", "")),
        ("agent_image", config.get("agent_image", "")),
    ]
    show_panel(key_value_table(rows), title="Miner CLI Config", border_style="blue")
    print_info("CLI flags always override config values.")
