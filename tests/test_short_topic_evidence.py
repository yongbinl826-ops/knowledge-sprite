"""A tool-name match alone cannot attest a short requested skill."""
import pytest

from backend.app.ranking import compound_english_match, assess_topic_evidence


@pytest.mark.parametrize("point", ["pandas 去重", "pandas to_datetime", "pygame 计分", "SQL JOIN"])
def test_two_term_topic_must_include_the_actual_requested_operation(point):
    tool = point.split()[0]
    assert not compound_english_match(point, [f"{tool} 视频教程：读取CSV"])


@pytest.mark.parametrize("point,source", [
    ("pandas 去重", "pandas 去重视频教程"),
    ("pandas to_datetime", "pandas to_datetime() converts a string to datetime"),
    ("SQL JOIN", "SQL joins tutorial"),
])
def test_short_real_operation_and_bounded_plural_equivalence_remain_eligible(point, source):
    assert compound_english_match(point, [source])
