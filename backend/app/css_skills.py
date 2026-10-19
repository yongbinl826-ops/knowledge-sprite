"""Small documented CSS equivalences for independently evidenced teaching.

Call only with one eligible own title/body field, after provenance, ownership,
non-teaching and target-boundary checks. This module never establishes video
identity, page ownership, source availability or any other learning target.

Primary definitions:
https://www.w3.org/TR/css-flexbox-1/#flex-wrap-property
https://www.w3.org/TR/selectors-4/#the-focus-visible-pseudo
"""
from __future__ import annotations

import re


_FLEX_TARGET = re.compile(
    r"(?:css\s*)?(?:flex|flexbox)\s*布局\s*(?:与|和|及)\s*(?:换行|自动换行)", re.I)
_FOCUS_TARGET = re.compile(
    r"(?:css\s*)?:?focus-visible\s*(?:样式|焦点样式|伪类样式)", re.I)
_CLAUSE = re.compile(r"[。！？!?；;\r\n]|\.(?=\s|$)")
_URL = re.compile(r"https?://\S+|\bwww\.\S+", re.I)
_FOREIGN = re.compile(r"\b(?:react[\s_-]*native|reactnative|flutter|swiftui|yoga)\b", re.I)
_NON_TEACHING = re.compile(
    r"先修|前置|预备知识|预先|事先|已经掌握|已掌握|已熟悉|需要掌握|需掌握|要求掌握"
    r"|先(?:学习|掌握|熟悉|了解)|(?:不|未)(?:会|曾|再)?(?:讲|教|介绍|包含|涉及|覆盖|提供)"
    r"|尚未|暂不|后续|以后再|下节|下期|待办|待实现|作业|练习题|仅供参考|相关(?:课程|视频)|推荐(?:课程|视频)"
    r"|(?:api|属性|符号|术语|功能)(?:清单|列表|索引)|目录索引"
    r"|\b(?:prerequisites?|prior\s+knowledge|already|assumes?|requires?|not|never|without|"
    r"todo|homework|future\s+lesson|next\s+lesson|coming\s+soon|api\s+list|symbol\s+index|"
    r"reference\s+only|related\s+(?:courses?|videos?))\b"
    r"|\b(?:doesn['’]t|don['’]t|won['’]t|cannot)\b", re.I)
_FLEX_PROPERTY = re.compile(r"(?<![A-Za-z0-9_.-])flex-wrap(?![A-Za-z0-9_-])", re.I)
_FOCUS_SELECTOR = re.compile(r"(?<![A-Za-z0-9_.-]):?focus-visible(?![A-Za-z0-9_-])", re.I)
_FLEX_CONTEXT = re.compile(
    r"(?<![A-Za-z0-9_-])(?:css(?:\s*3)?|flexbox)(?![A-Za-z0-9_-])"
    r"|(?<![A-Za-z0-9_-])flex\s*(?:布局|layout)(?![A-Za-z0-9_-])", re.I)
_CSS_CONTEXT = re.compile(
    r"(?<![A-Za-z0-9_-])css(?:\s*3)?(?![A-Za-z0-9_-])|(?:伪类)?选择器(?:的)?样式|伪类样式", re.I)
_FLEX_TEACHING = re.compile(
    r"理解|讲解|教学|教程|用法|使用|设置|控制|换行|从单行到多行|单行.{0,8}多行"
    r"|\b(?:understand(?:ing)?|teach(?:ing)?|tutorial|how\s+to|wrapping|single.line|multi.line)\b", re.I)
_FOCUS_TEACHING = re.compile(
    r"(?:控制|显示|指示|设置|可见|高亮|样式).{0,12}焦点|焦点.{0,12}(?:控制|显示|指示|设置|可见|高亮|样式)"
    r"|\bfocus\s+(?:styles?|indicators?|rings?)\b", re.I)


def _target_kind(target: str) -> str | None:
    if _FLEX_TARGET.fullmatch(target.strip()):
        return "flex"
    if _FOCUS_TARGET.fullmatch(target.strip()):
        return "focus"
    return None


def css_target_non_teaching(target: str, teaching: str) -> bool:
    """Veto an explicit own-field exclusion/requirement of the same literal API.

    This companion is needed because a literal flex-wrap exclusion may not
    contain the Chinese target's word 换行. It adds no positive coverage.
    """
    if not isinstance(target, str) or not isinstance(teaching, str):
        return False
    kind = _target_kind(target)
    if kind is None:
        return False
    literal = _FLEX_PROPERTY if kind == "flex" else _FOCUS_SELECTOR
    return any(literal.search(clause) and _NON_TEACHING.search(clause)
               for clause in _CLAUSE.split(_URL.sub(" ", teaching)) if len(clause) <= 800)


def css_target_rule(target: str, teaching: str) -> str | None:
    """Return one narrow rule for an exact target and a local teaching clause.

    A caller must not concatenate chapters, inherited parent titles or query
    text. Sentence boundaries are also enforced here; no context is borrowed
    from another sentence. URL text is discarded rather than used as context.
    """
    if not isinstance(target, str) or not isinstance(teaching, str):
        return None
    kind = _target_kind(target)
    if kind is None:
        return None
    for clause in _CLAUSE.split(_URL.sub(" ", teaching)):
        if not clause.strip() or len(clause) > 800 or _FOREIGN.search(clause) or _NON_TEACHING.search(clause):
            continue
        if kind == "flex" and _FLEX_PROPERTY.search(clause) and _FLEX_CONTEXT.search(clause) and _FLEX_TEACHING.search(clause):
            return "css_flex_wrap_is_line_wrapping"
        if kind == "focus" and _FOCUS_SELECTOR.search(clause) and _CSS_CONTEXT.search(clause) and _FOCUS_TEACHING.search(clause):
            return "css_focus_visible_is_focus_styling"
    return None
