import pytest

from backend.app.project_search import searchable_unit_name


@pytest.mark.parametrize("name,concepts,plan,expected", [
    ("分数统计与文字显示", ["pygame.font.Font 渲染", "blit 绘制文字"], "", "pygame 分数统计与文字显示"),
    ("Rect 矩形与坐标定位绘制", ["pygame.Rect 属性"], "", "pygame Rect 矩形与坐标定位绘制"),
    ("键盘长按移动挡板与边界限制", ["key.get_pressed 按键状态", "rect.clamp_ip 或边界判断"], "Python 3 与 pygame", "pygame 键盘长按移动挡板与边界限制"),
    ("游戏结束、空格重开与状态管理", ["KEYDOWN 事件判断空格", "重置函数"], "采用 pygame", "pygame 游戏结束、空格重开与状态管理"),
    ("键盘输入", ["KEYDOWN 事件"], "SDL", "键盘输入"),
    ("状态管理", ["变量与状态"], "pygame", "状态管理"),
    ("游戏状态标记与漏接结束画面", ["状态变量 playing/game_over"], "Python + pygame", "pygame 游戏状态标记与漏接结束画面"),
    ("空格重开与数据重置", ["重置函数"], "pygame 本地游戏", "pygame 空格重开与数据重置"),
    ("游戏状态标记", ["状态变量"], "pygame 或 Unity", "游戏状态标记"),
    ("JavaScript 键盘移动", ["pygame.key.get_pressed"], "pygame", "JavaScript 键盘移动"),
    ("pygame 键盘移动", ["pygame.key.get_pressed"], "pygame", "pygame 键盘移动"),
    ("pygame键盘移动", ["pygame.key.get_pressed"], "pygame", "pygame 键盘移动"),
    ("重开", ["KEYDOWN事件"], "用pygame做游戏", "pygame 重开"),
    ("分数显示", ["使用pygame.font.Font"], "", "pygame 分数显示"),
    ("绘图", ["matplotlib.pyplot.plot"], "", "matplotlib 绘图"),
    ("数据输入", ["pandas.read_csv", "numpy.array"], "", "数据输入"),
    ("历史单元", [], "pygame", "历史单元"),
    ("空格重开", ["文档链接 https://pygame.example/KEYDOWN"], "", "空格重开"),
])
def test_search_name_preserves_unit_scoped_tool(name, concepts, plan, expected):
    point = {"name": name, "concepts": concepts}
    assert searchable_unit_name(point, plan) == expected
    assert point == {"name": name, "concepts": concepts}


def test_enrichment_never_truncates_original_target():
    name = "长" * 160
    assert searchable_unit_name({"name": name, "concepts": ["pygame.font.Font"]}) == name


@pytest.mark.parametrize("technology,name,expected", [
    ("Arduino", "串口命令缓冲", "Arduino 串口命令缓冲"),
    ("pandas", "分组聚合", "pandas 分组聚合"),
    ("JavaScript", "表单校验与 fetch 请求", "JavaScript 表单校验与 fetch 请求"),
    ("Bevy", "角色碰撞", "Bevy 角色碰撞"),
    ("pygame", "pygame初始化", "pygame 初始化"),
    ("C++", "C++对象与构造", "C++ 对象与构造"),
    ("", "概率与随机", "概率与随机"),
    ("通用", "概率与随机", "概率与随机"),
])
def test_explicit_unit_technology_is_independent_of_the_project_stack(technology, name, expected):
    assert searchable_unit_name({"name": name, "technology": technology}, "Python + pygame + Arduino + JavaScript") == expected


def test_explicit_technology_never_silently_exceeds_target_limit():
    with pytest.raises(ValueError):
        searchable_unit_name({"name": "长" * 160, "technology": "Arduino"})
