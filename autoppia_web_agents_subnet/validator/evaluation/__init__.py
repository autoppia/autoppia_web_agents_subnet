from .eval import evaluate_task_solutions  # noqa: F401
from .penalties import apply_same_solution_penalty, apply_same_solution_penalty_with_meta  # noqa: F401
from .rewards import calculate_rewards_for_task  # noqa: F401
from .synapse_handlers import send_feedback_synapse_to_miners, send_start_round_synapse_to_miners, send_task_synapse_to_miners  # noqa: F401

# Optional mixin (added for tests)
try:
    from .mixin import EvaluationPhaseMixin  # noqa: F401
except Exception:  # pragma: no cover - missing during partial installs
    pass
