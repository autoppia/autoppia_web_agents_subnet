import contextlib
import logging
import os
import re
from pathlib import Path

import bittensor as bt


class ColoredLogger:
    """A simple logger that uses ANSI colors when calling bt.logging methods."""

    BLUE = "blue"
    YELLOW = "yellow"
    RED = "red"
    GREEN = "green"
    CYAN = "cyan"
    MAGENTA = "magenta"
    WHITE = "white"
    PURPLE = "purple"
    GRAY = "gray"
    GOLD = "gold"
    ORANGE = "orange"
    RESET = "reset"

    _COLORS = {  # noqa: RUF012
        "blue": "\033[94m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "green": "\033[92m",
        "cyan": "\033[96m",
        "magenta": "\033[95m",
        "white": "\033[97m",
        "gray": "\033[90m",
        "gold": "\033[38;5;220m",  # Bright gold/yellow (256 colors)
        "orange": "\033[38;5;214m",  # Orange (256 colors)
        "reset": "\033[0m",
        "purple": "\033[35m",
    }

    _round_log_file: Path | None = None
    _round_log_handler: logging.Handler | None = None
    _round_log_logger: logging.Logger | None = None
    _round_log_bt_logger: logging.Logger | None = None
    _round_log_loguru_id: int | None = None
    _ROUND_LOG_UPLOAD_TAIL_LIMITS = (2_000_000, 1_000_000, 512_000, 256_000)

    @staticmethod
    def _resolve_round_log_logger() -> logging.Logger:
        return logging.getLogger()

    @staticmethod
    def _close_round_log_file() -> None:
        handler = ColoredLogger._round_log_handler
        if handler is not None:
            for logger in (
                ColoredLogger._round_log_logger,
                ColoredLogger._round_log_bt_logger,
            ):
                if logger is not None:
                    with contextlib.suppress(Exception):
                        logger.removeHandler(handler)
            with contextlib.suppress(Exception):
                handler.close()
        ColoredLogger._round_log_handler = None
        ColoredLogger._round_log_logger = None
        ColoredLogger._round_log_bt_logger = None
        if ColoredLogger._round_log_loguru_id is not None:
            try:
                from loguru import logger as _loguru

                _loguru.remove(ColoredLogger._round_log_loguru_id)
            except Exception:
                pass
            ColoredLogger._round_log_loguru_id = None

    @staticmethod
    def _colored_msg(message: str, color: str) -> str:
        """Return the colored message based on the color provided."""
        if color not in ColoredLogger._COLORS:
            # Default to no color if unsupported color is provided
            return message
        return f"{ColoredLogger._COLORS[color]}{message}{ColoredLogger._COLORS['reset']}"

    @staticmethod
    def info(message: str, color: str = "blue") -> None:
        bt.logging.info(ColoredLogger._colored_msg(message, color))

    @staticmethod
    def warning(message: str, color: str = "yellow") -> None:
        bt.logging.warning(ColoredLogger._colored_msg(message, color))

    @staticmethod
    def error(message: str, color: str = "red") -> None:
        bt.logging.error(ColoredLogger._colored_msg(message, color))

    @staticmethod
    def success(message: str, color: str = "green") -> None:
        bt.logging.success(ColoredLogger._colored_msg(message, color))

    @staticmethod
    def debug(message: str, color: str = "gray") -> None:
        bt.logging.debug(ColoredLogger._colored_msg(message, color))

    @staticmethod
    def set_round_log_file(round_id: str) -> None:
        """
        Persist all logger output for the current round to a dedicated log file.
        - Fresh file per round start: if the same season/round identifiers are reused
          after a reset, we overwrite the old file to avoid mixing stale and new logs.
        - Writes from: root logger, bittensor logger, and loguru (IWA etc.) to the same file.
        - The file is read and uploaded at round finish; if upload fails, the file
          remains on disk with the full log. clear_round_log_file only stops writing.
        """
        root_logger = ColoredLogger._resolve_round_log_logger()
        ColoredLogger._close_round_log_file()

        season = "unknown"
        round_number = "unknown"
        match = re.match(r"^validator_round_(\d+)_(\d+)_", round_id)
        if match:
            season = match.group(1)
            round_number = match.group(2)

        backup_root = os.getenv("IWAP_BACKUP_DIR")
        base_dir = Path(backup_root) if backup_root else Path("data")
        round_dir = base_dir / f"season_{season}" / f"round_{round_number}"
        round_dir.mkdir(parents=True, exist_ok=True)
        log_path = round_dir / "round.log"

        handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)

        # Also attach to bittensor's logger so all bt.logging.* output is written
        # to the same round log file (bittensor often does not propagate to root).
        bt_logger = logging.getLogger("bittensor")
        bt_logger.addHandler(handler)

        # IWA and other code use loguru; add a sink so those logs go to the same file.
        loguru_id: int | None = None
        try:
            from loguru import logger as _loguru

            loguru_id = _loguru.add(
                str(log_path),
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
                level="DEBUG",
                mode="w",
                encoding="utf-8",
            )
        except Exception:
            loguru_id = None

        ColoredLogger._round_log_file = log_path
        ColoredLogger._round_log_handler = handler
        ColoredLogger._round_log_logger = root_logger
        ColoredLogger._round_log_bt_logger = bt_logger
        ColoredLogger._round_log_loguru_id = loguru_id

    @staticmethod
    def get_round_log_file() -> str | None:
        if ColoredLogger._round_log_file is None:
            return None
        return str(ColoredLogger._round_log_file)

    @staticmethod
    def clear_round_log_file() -> None:
        ColoredLogger._close_round_log_file()
        ColoredLogger._round_log_file = None

    @staticmethod
    def _trim_utf8_tail(content: str, *, max_bytes: int) -> str:
        if max_bytes <= 0:
            return ""
        raw = content.encode("utf-8", errors="replace")
        if len(raw) <= max_bytes:
            return content
        tail = raw[-max_bytes:]
        return tail.decode("utf-8", errors="ignore")

    @staticmethod
    def build_round_log_upload_variants(content: str) -> list[tuple[str, str]]:
        """
        Build progressively smaller payload variants for S3/IWAP round-log upload.

        The first entry is always the full log. Smaller entries keep the newest tail
        and prepend a short header explaining that the upload was truncated after a
        413/size failure, so we still persist something useful instead of losing the
        round log entirely.
        """
        raw = content.encode("utf-8", errors="replace")
        total_bytes = len(raw)
        variants: list[tuple[str, str]] = [("full", content)]
        seen_payloads: set[str] = {content}

        for limit in ColoredLogger._ROUND_LOG_UPLOAD_TAIL_LIMITS:
            if total_bytes <= limit:
                continue
            header = f"[AUTOPPIA ROUND LOG TRUNCATED FOR S3 UPLOAD]\noriginal_bytes={total_bytes}\nupload_bytes_limit={limit}\nupload_mode=tail_only_after_413\n\n"
            header_bytes = len(header.encode("utf-8", errors="replace"))
            tail_budget = max(limit - header_bytes, 0)
            tail = ColoredLogger._trim_utf8_tail(content, max_bytes=tail_budget)
            payload = header + tail
            if payload in seen_payloads:
                continue
            seen_payloads.add(payload)
            variants.append((f"tail_{limit}", payload))

        return variants
