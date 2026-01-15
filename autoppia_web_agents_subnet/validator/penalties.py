"""Compat shim exporting penalties helpers."""

from autoppia_web_agents_subnet.validator.evaluation import penalties as _pen

SAME_SOLUTION_PENALTY = _pen.SAME_SOLUTION_PENALTY
SAME_SOLUTION_SIM_THRESHOLD = _pen.SAME_SOLUTION_SIM_THRESHOLD


def apply_same_solution_penalty(solutions, eval_scores):
    # Sync mutable config if overridden in this module
    _pen.SAME_SOLUTION_PENALTY = globals().get("SAME_SOLUTION_PENALTY", _pen.SAME_SOLUTION_PENALTY)
    _pen.SAME_SOLUTION_SIM_THRESHOLD = globals().get(
        "SAME_SOLUTION_SIM_THRESHOLD", _pen.SAME_SOLUTION_SIM_THRESHOLD
    )
    return _pen.apply_same_solution_penalty(solutions, eval_scores)


def apply_same_solution_penalty_with_meta(solutions, eval_scores):
    _pen.SAME_SOLUTION_PENALTY = globals().get("SAME_SOLUTION_PENALTY", _pen.SAME_SOLUTION_PENALTY)
    _pen.SAME_SOLUTION_SIM_THRESHOLD = globals().get(
        "SAME_SOLUTION_SIM_THRESHOLD", _pen.SAME_SOLUTION_SIM_THRESHOLD
    )
    return _pen.apply_same_solution_penalty_with_meta(solutions, eval_scores)
