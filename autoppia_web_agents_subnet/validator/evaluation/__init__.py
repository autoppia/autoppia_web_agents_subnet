from .penalties import apply_same_solution_penalty, apply_same_solution_penalty_with_meta  # noqa: F401
from .rewards import calculate_rewards_for_task  # noqa: F401

# Optional mixin (added for tests)
try:
    from .mixin import EvaluationPhaseMixin  # noqa: F401
except Exception:  # pragma: no cover - missing during partial installs
    pass
