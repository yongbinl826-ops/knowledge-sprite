"""Synthetic transport contract only; not live model accuracy."""
import json

import httpx
import pytest

from backend.app import llm as module
from backend.app.config import Settings
from backend.app.models import SearchRequest



@pytest.mark.parametrize('topic,technology,expected', [
    ('Canvas.toBlob() 图像导出与浏览器下载', 'JavaScript', ['Canvas.toBlob']),
    ('pd.read_csv() 从内存缓冲读取数据', 'Python', ['pd.read_csv']),
    ('Rust HashMap 插入与遍历', 'Rust', ['Rust', 'HashMap']),
    ('C++17 vector 下标读取', 'C++', ['C++17', 'vector']),
    ('torch.load() 模型加载', 'PyTorch', ['torch.load']),
    ('Pointer 事件统一鼠标与触摸输入', 'JavaScript', ['Pointer']),
    ('HTML 表单取值', 'HTML', ['HTML']),
    ('撤销与重做历史', 'JavaScript', []),
    ('.NET 异步任务与取消机制', '.NET', ['.NET']),
    ('python-docx 段落样式与表格生成', 'Python', ['python-docx']),
])
async def test_original_identifiers_reach_one_discovery_request(monkeypatch, topic, technology, expected):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            'suggestions': [{'point_id': 'kp_0', 'urls': [], 'queries': ['JavaScript teaching example']}]
        })}}]})

    original = SearchRequest(knowledge_points=[topic], preferred_platforms=['bilibili'],
                            topic_technologies={topic: technology}, technical_version='')
    before = original.model_dump()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result, diagnostics = await module.OpenAICompatibleLLM(Settings(llm_api_key='synthetic-key', llm_model='synthetic-model'), client).suggest_video_discovery_with_diagnostics([topic], original)
    assert len(calls) == 1
    payload = calls[0]
    data = json.loads(payload['messages'][1]['content'])
    assert data['points'][0]['required_literals'] == expected
    assert data['points'][0]['knowledge_point'] == topic
    assert data['points'][0]['topic_technology'] == technology
    assert original.model_dump() == before
    assert 'existing required API is not optional' in payload['messages'][0]['content']
    assert 'every supplied required_literals entry must occur' in payload['messages'][0]['content']
    assert 'A single well-known API name is optional' not in payload['messages'][0]['content']
    assert 'tools' not in payload
    assert result[topic]['urls'] == []
    assert diagnostics['query_normalization']['accepted_queries'] == 1

