"""Offline inspection admission only; none of these rows prove teaching."""
import pytest

from backend.app.mooc_relevance import teaching_probe_eligible


@pytest.mark.parametrize("snippet,expected", [
    ("本课程讲解 STM32F4，板卡接口兼容 Arduino 扩展板。", False),
    ("本课程讲解 STM32F4。扩展板接口兼容 Arduino。", False),
    ("本课程讲解 Arduino Uno 按钮去抖。", True),
    ("通过案例，层层递进掌握基于Arduino的智能系统设计和实现。", True),
    ("本课程讲解 STM32F4，Arduino 扩展板接口兼容。", False),
    ("本课程不讲 Arduino，讲解其他工具。", False),
    ("本课程讲解其他工具。相关视频：Arduino，讲解按钮开发。", False),
    ("下节课讲解 Arduino 按钮去抖。", False),
    ("Next lesson: we teach Arduino button debounce.", False),
    ("开发板接口兼容 Arduino，讲解 STM32F4 的按键处理。", False),
    ("参考文档为 Arduino，讲解 STM32F4 的按键处理。", False),
    ("Arduino，讲解按钮开发的具体方法。", True),
])
def test_instruction_object_stays_in_its_own_local_clause(snippet, expected):
    url = "https://www.icourse163.org/course/EXAMPLE-123"
    p = {"knowledge_point_id": "p", "text": "Arduino 按钮消抖"}
    r = {"url": url, "canonical_url": url, "resource_type": "course", "fetch_status": "not_fetched"}
    e = [{"kind": "search", "evidence_id": "s", "knowledge_point_id": "p", "url": url,
          "title": "智能系统课程", "snippet": snippet}]
    assert teaching_probe_eligible(p, r, e) is expected


@pytest.mark.parametrize("snippet,expected", [
    ("Python第三方库Pygame，讲解单机2D游戏设计和实现的基本概念和开发方法。", True),
    ("Python第三方库OtherGame，讲解单机2D游戏，扩展接口兼容Pygame。", False),
    ("预备知识：Pygame，讲解单机2D游戏。", False),
    ("本课程不讲Pygame，讲解单机2D游戏。", False),
    ("Python第三方库Pygame，讲解 OtherFlow 按键处理。", False),
])
def test_explicit_own_subject_can_precede_its_instructional_predicate(snippet, expected):
    url = "https://www.icourse163.org/course/EXAMPLE-123"
    p = {"knowledge_point_id": "p", "text": "pygame 矩形碰撞检测"}
    r = {"url": url, "canonical_url": url, "resource_type": "course", "fetch_status": "not_fetched"}
    e = [{"kind": "search", "evidence_id": "s", "knowledge_point_id": "p", "url": url,
          "title": "Python游戏开发入门", "snippet": snippet}]
    assert teaching_probe_eligible(p, r, e) is expected


@pytest.mark.parametrize("title,snippet,expected", [
    ("STM32F4与Arduino兼容接口专题", "介绍接口兼容关系。", False),
    ("STM32F4课程：参考Arduino文档", "介绍接口资料。", False),
    ("Comparison with Arduino", "This course explains another framework.", False),
    ("Arduino兼容接口课程", "本课程讲解Arduino按钮输入处理。", True),
    ("下节课讲解Arduino", "本课程讲解Arduino按钮输入处理。", False),
])
def test_reference_title_is_not_own_teaching_but_independent_instruction_can_admit(title, snippet, expected):
    url = "https://www.icourse163.org/course/EXAMPLE-123"
    p = {"knowledge_point_id": "p", "text": "Arduino 按钮消抖"}
    r = {"url": url, "canonical_url": url, "resource_type": "course", "fetch_status": "not_fetched"}
    e = [{"kind": "search", "evidence_id": "s", "knowledge_point_id": "p", "url": url, "title": title, "snippet": snippet}]
    assert teaching_probe_eligible(p, r, e) is expected
