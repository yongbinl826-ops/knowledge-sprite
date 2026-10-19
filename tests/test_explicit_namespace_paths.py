"""An explicit source namespace may qualify the student's same attribute path."""
import pytest
from backend.app.ranking import compound_english_match


@pytest.mark.parametrize("point, source", [
    ("pygame display.set_mode", "pygame.display.set_mode((600, 600))"),
    ("pygame pygame.init 与 display.set_mode", "pygame.init() and pygame.display.set_mode((600, 600))"),
    ("pygame KEYDOWN", "pygame.KEYDOWN event tutorial"),
    ("numpy linalg.norm", "numpy.linalg.norm(array) tutorial"),
])
def test_same_explicit_owner_and_entire_attribute_path_are_eligible(point, source):
    assert compound_english_match(point, [source])


@pytest.mark.parametrize("point, source", [
    ("pygame display.set_mode", "OtherTool.display.set_mode() tutorial"),
    ("pygame 单次移动与边界拦截", "pygame.KEYDOWN event tutorial"),
    ("pandas 去重", "pandas.read_csv tutorial"),
    ("pandas read_csv", "pandas.other.read_csv tutorial"),
    ("pygame display", "pygame.display.set_mode tutorial"),
    ("pandas pd.to_datetime", "pandas.to_datetime tutorial"),
])
def test_namespaces_do_not_supply_missing_action_middle_attribute_or_implicit_alias(point, source):
    assert not compound_english_match(point, [source])
