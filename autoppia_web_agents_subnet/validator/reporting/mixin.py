from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ReportingMixin:
    """Placeholder mixin for future reporting support."""

    @staticmethod
    def resend_round_report(round_number: int) -> bool:
        logger.error("Reporting is not implemented yet; cannot resend report for round %s", round_number)
        return False

