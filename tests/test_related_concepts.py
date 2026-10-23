"""Bilingual relevance preserves ordinary concepts without exact-proof claims."""
import pytest
from test_related_recommendations import candidate
from backend.app.related_recommendations import related_recommendation

@pytest.mark.parametrize('point,tech,title,body,expected',[
    ('游戏主循环','pygame','Pygame game loop','',True),
    ('游戏主循环','pygame','Pygame introduction','Python basics only',False),
    ('矩形区域表示','pygame','Pygame rectangle objects','',True),
    ('矩形碰撞检测','pygame','Pygame rectangle area and file detection','',False),
    ('矩形碰撞检测','pygame','Pygame collision detection','',True),
    ('键盘输入处理','pygame','Pygame movement','keys = pygame.key.get_pressed()',True),
    ('键盘输入处理','pygame','Pygame course','not teaching key presses',False),
    ('键盘输入处理','pygame','Pygame tutorial','keyboard input is not covered.',False),
    ('键盘输入处理','pygame','Pygame tutorial','keyboard input — not taught.',False),
    ('键盘输入处理','pygame','Pygame tutorial','keyboard input is covered.',True),
    ('键盘输入处理','pygame','Unity keyboard handling','',False),
    ('键盘输入处理','pygame','Sponsored Pygame key presses','',False),
    ('文本渲染','pygame','Pygame scoring','text = font.render(str(score), True, (255,255,255))',True),
    ('文本分段','Python','Python Text Splitting','',True),
    ('文本分段','Python','Python text chunking','',True),
    ('文本分段','Python','Python tutorial','Text splitting is not covered.',False),
    ('文本分段','Python','JavaScript Text Splitting','',False),
    ('文本分段','Python','Python image segmentation','',False),
    ('文本分段','Python','NLP - 文本预处理和文本分类（使用Python）（中英字幕）','',False),
    ('文本分段','Python','Python 文本切分与段落处理','',True),
    ('文本分割','Python','Python 文本分类','',False),
    ('随机数生成','Python','Python random numbers','random.randint(0, 5)',True),
    ('列表增删遍历','Python','Python list operations','items.append(value)',True),
    ('列表增删遍历','Python','Python snake','Our object will contain a list of segments.',True),
    ('列表增删遍历','Python','Python course','Here is a list of related courses.',False),
    ('有限状态机','pygame','Pygame finite state machine','',True),
    ('游戏计数变量','Python','Pygame scoring and health bars','score += 1',True),
    ('DataFrame 数据结构','pandas','Pandas basics','DataFrames and their structures',True),
    ('CSV 文件读取','pandas','Pandas data import','df = pd.read_csv(filename)',True),
    ('CSV 文件读取','pandas','利用pandas读取csv格式文件','',True),
    ('CSV 文件读取','pandas','使用pandas库读取csv文件并筛选行和列数据','',True),
    ('CSV 文件读取','pandas','Pandas CSV 文件导出','df.to_csv(filename)',False),
    ('缺失值处理','pandas','Pandas data cleaning','identify and rectify null values',True),
    ('日期时间属性','pandas','Pandas dates','pd.to_datetime(column)',True),
    ('布尔索引过滤','pandas','Pandas projects','Filtering and Sorting with Pokemon Data',True),
    ('Streamlit 图表展示','Streamlit','Pandas plotting charts','',False),
    ('Streamlit 交互控件','Streamlit','Streamlit widgets','st.slider(label)',True),
    ('CSV 文件导出与下载','Streamlit','Streamlit downloads','st.download_button(label, df.to_csv())',True),
    ('分组聚合','pandas','Pandas group advertising assets','aggregate images',False),
    ('DataFrame 数据结构','pandas','Pandas resources','https://example.org/DataFrames',False),
])
def test_bilingual_concept_reference_boundaries(point,tech,title,body,expected):
    result=related_recommendation(*candidate(title,body,name=point,technology=tech))
    assert bool(result) is expected
    if result:
        assert result['reference']['exact_teaching_verified'] is False
        assert '未验证精确讲授' in result['reference']['reason']
