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
        "reset": "\033[0m",
        "purple": "\033[35m",
    }

    @staticmethod
    def _colored_msg(message: str, color: str) -> str:
        """Return the colored message based on the color provided."""
        if color not in ColoredLogger._COLORS:
            # Default to no color if unsupported color is provided
            return message
        return (
            f"{ColoredLogger._COLORS[color]}{message}{ColoredLogger._COLORS['reset']}"
        )

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
