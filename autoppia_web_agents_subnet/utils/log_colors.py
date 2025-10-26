"""
Colored module tags for logging system.

Each module has a distinct color for easy visual identification in logs.
"""

# ANSI color codes
CYAN = "\033[36m"           # IPFS operations
BRIGHT_CYAN = "\033[96m"    # CONSENSUS operations
MAGENTA = "\033[35m"        # IWAP/API calls
YELLOW = "\033[33m"         # CHECKPOINT/state
GREEN = "\033[32m"          # EVALUATION/testing
BLUE = "\033[34m"           # General info
RESET = "\033[0m"


def ipfs_tag(action: str, msg: str) -> str:
    """
    Add colored IPFS tag to message.

    Args:
        action: UPLOAD, DOWNLOAD, or BLOCKCHAIN
        msg: The log message

    Returns:
        Formatted string with colored tag
    """
    return f"{CYAN}[IPFS] [{action}]{RESET} {msg}"


def consensus_tag(msg: str) -> str:
    """Add colored CONSENSUS tag to message"""
    return f"{BRIGHT_CYAN}[CONSENSUS]{RESET} {msg}"


def iwap_tag(context: str, msg: str) -> str:
    """Add colored IWAP tag to message"""
    return f"{MAGENTA}[IWAP] [{context}]{RESET} {msg}"


def checkpoint_tag(msg: str) -> str:
    """Add colored CHECKPOINT tag to message"""
    return f"{YELLOW}[CHECKPOINT]{RESET} {msg}"


def evaluation_tag(context: str, msg: str) -> str:
    """Add colored EVALUATION tag to message"""
    return f"{GREEN}[EVALUATION] [{context}]{RESET} {msg}"


def round_details_tag(msg: str) -> str:
    """Add colored ROUND DETAILS tag to message"""
    return f"{BLUE}[ROUND DETAILS]{RESET} {msg}"
