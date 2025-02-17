import logging
import traceback
from functools import wraps

# -----------------------------------------
# Logger Setup for Actions
# -----------------------------------------
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"

action_logger = logging.getLogger("action_logger")
action_logger.setLevel(logging.INFO)

# Create a console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

# Add the handler to the logger (if not already added)
if not action_logger.hasHandlers():
    action_logger.addHandler(console_handler)


def log_action(action_name):
    """Decorator to log the start, success, and failure of an action asynchronously."""

    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            action_logger.info(f"[{action_name}] Started")
            console_handler.flush()

            try:
                result = await func(self, *args, **kwargs)
                action_logger.info(f"[{action_name}] Success - Result: {result}")
                console_handler.flush()
                return result
            except Exception as e:
                error_details = traceback.format_exc()
                action_logger.error(f"[{action_name}] Failed - Error: {str(e)}\n{error_details}")
                console_handler.flush()
                raise

        return wrapper

    return decorator
