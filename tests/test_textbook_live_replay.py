"""Recorded v9-v11 drafts replayed once, without claiming semantic approval."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app import project_analysis as module
from backend.app.project_analysis import ProjectAnalyzer
from backend.app.project_models import ProjectInput
from tests.test_project_analysis import settings

FIXTURES = Path(__file__).parent / "fixtures" / "textbook-live-20261023"


def recorded(version):
    return json.loads((FIXTURES / f"draft-v{version}.json").read_text(encoding="utf-8"))


async def replay(monkeypatch, analysis, source):
    calls, attempts = [], []
    original = deepcopy(analysis)
    async def complete(_settings, _prompt, payload, *_args, **_kwargs):
        calls.append(deepcopy(payload))
        assert len(calls) == 1
        return deepcopy(analysis)
    def forbidden(*_args, **_kwargs):
        pytest.fail("Saved model content must not be judged or rewritten")
    monkeypatch.setattr(module, "complete_json", complete)
    monkeypatch.setattr(module, "_local_quality_issues", forbidden)
    result = await ProjectAnalyzer(settings()).analyze(
        ProjectInput.model_validate(source), on_analysis_attempt=attempts.append)
    assert len(calls) == len(attempts) == 1
    assert (attempts[0]["phase"], attempts[0]["outcome"]) == ("generation", "accepted")
    assert attempts[0]["analysis"] == analysis == original
    assert "advisories" not in attempts[0] and "issues" not in attempts[0]
    assert not {"repair_required", "validation_feedback", "previous_analysis"} & set(calls[0])
    assert [p.name for p in result.knowledge_points] == [p["name"] for p in analysis["knowledge_points"]]
    assert [p.description for p in result.knowledge_points] == [p["description"] for p in analysis["knowledge_points"]]
    assert [p.technology for p in result.knowledge_points] == [p.get("technology", "") for p in analysis["knowledge_points"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [9, 10, 11])
async def test_full_saved_draft_is_preserved_without_conditional_repair(monkeypatch, version):
    record = recorded(version)
    original = deepcopy(record)
    await replay(monkeypatch, record["analysis"], record["input"])
    assert record == original


@pytest.mark.asyncio
@pytest.mark.parametrize("version,name", [
    (9, "游戏状态重置"), (10, "游戏重置"), (10, "帧率控制"), (11, "状态重置"),
    (9, "事件队列与键盘输入"), (9, "基于时间步长的运动更新"),
    (9, "矩形表示与矩形碰撞检测"), (9, "文本渲染与分数显示"),
    (10, "矩形表示与绘制"), (10, "计数器与累加"),
])
async def test_prior_hard_and_advisory_examples_are_delivered_without_judgement(monkeypatch, version, name):
    record = recorded(version)
    original = deepcopy(record)
    analysis = deepcopy(record["analysis"])
    analysis["knowledge_points"] = [next(p for p in analysis["knowledge_points"] if p["name"] == name)]
    await replay(monkeypatch, analysis, record["input"])
    assert record == original
