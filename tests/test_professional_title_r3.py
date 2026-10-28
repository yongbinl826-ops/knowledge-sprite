"""Prior title examples remain literal content in single-pass analysis."""
import pytest

from backend.app import project_analysis as module
from tests.test_professional_knowledge_contract import body
from tests.test_professional_title_quality import generate_once


@pytest.mark.parametrize("title", [
    "Python 基础知识", "英语基础", "English basics", "Ｅｎｇｌｉｓｈ　ｂａｓｉｃｓ",
    "score = 0", "x = x + 1", "print('hello')", "lives -= 1", "count: int = 0",
    "sensors.read()", "result = measure()", "pygame.time.Clock()", "分数 = 0",
])
@pytest.mark.asyncio
async def test_broad_or_statement_title_is_preserved_once_without_execution(title, monkeypatch):
    supplied = body()
    supplied["knowledge_points"][0]["name"] = title
    def forbidden(*_args, **_kwargs):
        pytest.fail("Title syntax must not be parsed for semantic judgement")
    monkeypatch.setattr(module, "_single_statement_title", forbidden)
    await generate_once(supplied)
    assert module.ANALYSIS_MAX_MODEL_CALLS == module.ANALYSIS_MAX_ATTEMPTS == 1


@pytest.mark.parametrize("title", [
    "状态机", "Python 基础数据类型的数值转换", "英语音标", "pygame.Rect",
    "pandas.to_datetime 日期时间解析", "函数调用", "变量作用域", "JavaScript 严格相等比较",
    "占空比", "React useState 状态管理", "矩形碰撞检测", "函数调用 (Function Call)",
    "CSS: Grid", "HTML: forms", "Python 列表与循环的游戏状态建模", "英语音标与重音规则",
    "函数调用与参数传递", "变量作用域与状态建模", "PWM 占空比与亮度控制",
])
@pytest.mark.asyncio
async def test_professional_topics_are_not_rejected_for_substrings_or_api_identifiers(title, monkeypatch):
    supplied = body()
    supplied["knowledge_points"][0]["name"] = title
    def forbidden(*_args, **_kwargs):
        pytest.fail("Expanded pedagogical gates are outside the current contract")
    monkeypatch.setattr(module, "learning_quality_issues", forbidden)
    result, _ = await generate_once(supplied)
    assert result.knowledge_points[0].learning_skills == []


@pytest.mark.asyncio
async def test_statement_is_returned_without_quality_correction():
    supplied = body()
    supplied["knowledge_points"][0]["name"] = "x = x + 1"
    await generate_once(supplied)
