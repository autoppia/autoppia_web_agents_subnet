import logging
from pathlib import Path
import re
from typing import Optional

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

    _COLORS = {
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

    _round_log_file: Optional[Path] = None
    _round_log_handler: Optional[logging.Handler] = None
    _round_log_logger: Optional[logging.Logger] = None
    _round_log_bt_logger: Optional[logging.Logger] = None
    _round_log_loguru_id: Optional[int] = None

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
                    try:
                        logger.removeHandler(handler)
                    except Exception:
                        pass
            try:
                handler.close()
            except Exception:
                pass
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
        - Append-only: we never truncate; everything is written to the same file
          for the whole round, so you get "all logs up to the end" (or up to any error).
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

        log_dir = Path("data") / f"season_{season}" / f"round_{round_number}" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{round_id}.log"

        handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
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
        loguru_id: Optional[int] = None
        try:
            from loguru import logger as _loguru

            loguru_id = _loguru.add(
                str(log_path),
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
                level="DEBUG",
                mode="a",
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
    def get_round_log_file() -> Optional[str]:
        if ColoredLogger._round_log_file is None:
            return None
        return str(ColoredLogger._round_log_file)

    @staticmethod
    def clear_round_log_file() -> None:
        ColoredLogger._close_round_log_file()
        ColoredLogger._round_log_file = None
