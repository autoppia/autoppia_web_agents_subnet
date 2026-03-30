from __future__ import annotations

from urllib.parse import urlparse

from autoppia_web_agents_subnet.utils.env import _env_float, _env_int

# Must match validator and chain: 1 epoch = 360 blocks.
BLOCKS_PER_EPOCH = _env_int("BLOCKS_PER_EPOCH", 360, test_default=360)
ROUND_SIZE_EPOCHS = _env_float("ROUND_SIZE_EPOCHS", 5.0, test_default=5.0)
SEASON_SIZE_EPOCHS = _env_float("SEASON_SIZE_EPOCHS", 140.0, test_default=140.0)
MINIMUM_START_BLOCK = _env_int("MINIMUM_START_BLOCK", 7_758_721, test_default=7_758_721)


def season_block_length() -> int:
    return int(BLOCKS_PER_EPOCH * SEASON_SIZE_EPOCHS)


def round_block_length() -> int:
    return int(BLOCKS_PER_EPOCH * ROUND_SIZE_EPOCHS)


def compute_season(current_block: int) -> int:
    if current_block < MINIMUM_START_BLOCK:
        return 0
    return int((current_block - MINIMUM_START_BLOCK) // season_block_length()) + 1


def compute_season_start_block(season_number: int) -> int:
    if season_number <= 0:
        return MINIMUM_START_BLOCK
    return MINIMUM_START_BLOCK + (season_number - 1) * season_block_length()


def compute_current_round(current_block: int, season_number: int) -> int:
    season_start = compute_season_start_block(season_number)
    effective = max(current_block, season_start)
    return int((effective - season_start) // round_block_length()) + 1


def compute_next_round(current_block: int, season_number: int) -> int:
    return compute_current_round(current_block, season_number) + 1


def detect_github_ref_kind(raw_url: str) -> str:
    url = raw_url.strip()
    if url.startswith("git@github.com:"):
        path = url[len("git@github.com:") :].strip()
        segments = [segment for segment in path.split("/") if segment]
    else:
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        parsed = urlparse(url)
        segments = [segment for segment in (parsed.path or "").strip("/").split("/") if segment]

    if len(segments) >= 4 and (segments[2] or "").lower() == "commit":
        return "commit"
    return "tree"
