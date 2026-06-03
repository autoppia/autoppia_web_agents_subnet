from pathlib import Path

import pytest

from autoppia_web_agents_subnet.validator.settlement.king_overfit_judge import (
    KingOverfitLLMJudgeVerdict,
    build_repo_source_bundle,
)


@pytest.mark.unit
def test_repo_source_bundle_inlines_code_and_excludes_secrets(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "harvester.py").write_text(
        "PROJECTS = {'autocalendar': [{'name': 'navigate'}]}\n",
        encoding="utf-8",
    )
    (repo / "generic.py").write_text("def solve(task):\n    return []\n", encoding="utf-8")
    (repo / ".env").write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")

    bundle, meta = build_repo_source_bundle(
        repo,
        max_files=10,
        max_bundle_chars=10_000,
        max_file_chars=2_000,
    )

    assert "--- FILE: harvester.py ---" in bundle
    assert "autocalendar" in bundle
    assert "OPENAI_API_KEY" not in bundle
    assert "node_modules" not in bundle
    assert meta["files_included"] == 2


@pytest.mark.unit
def test_king_overfit_verdict_rejects_only_with_evidence_and_confidence():
    verdict = KingOverfitLLMJudgeVerdict(
        decision="reject",
        is_overfitted=True,
        confidence=0.95,
        summary="hardcoded benchmark",
        evidence=[{"file": "harvester.py", "reason": "hardcoded autocalendar"}],
    )
    assert verdict.rejects is True

    weak = KingOverfitLLMJudgeVerdict(
        decision="reject",
        is_overfitted=True,
        confidence=0.95,
        summary="no concrete evidence",
        evidence=[],
    )
    assert weak.rejects is False
