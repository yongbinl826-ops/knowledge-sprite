"""Preserve a learning unit's explicit tool when adapting it to text search.

Only the student's selected unit and its confirmed concepts define the target.
Project context is never evidence that an external source teaches that target.
"""
from __future__ import annotations

import re
from .technical_prefix import canonical_search_name, leading_technical_owner


_NAMESPACES = ("pygame", "pandas", "matplotlib", "numpy", "streamlit", "sqlite3", "flask", "fastapi")
_COMPETING = re.compile(r"(?<![A-Za-z0-9_])(?:javascript|typescript|react|vue|unity|godot|arduino|pygame|pandas|matplotlib|numpy|streamlit|sqlite3|flask|fastapi)(?![A-Za-z0-9_])", re.I)
_PYGAME_API = re.compile(r"(?<![A-Za-z0-9_])(?:key\.get_pressed|Rect\.colliderect|rect\.clamp_ip|KEYDOWN|K_SPACE|K_LEFT|K_RIGHT)(?![A-Za-z0-9_])")


class SearchTargetCollision(ValueError):
    """Distinct confirmed units cannot silently overwrite a target mapping."""


def searchable_learning_skills(points: dict[str, dict], search_names: dict[str, str]) -> dict[str, list[str]]:
    """Only explicitly reviewed skills define the new teaching axis."""
    observed, targets = {}, {}
    for point_id, search_name in search_names.items():
        skills = list(points[point_id].get("learning_skills") or [])
        if search_name in observed and observed[search_name] != skills:
            raise SearchTargetCollision("Distinct learning units share a search name but have different learning skills")
        observed[search_name] = skills
        if skills:
            targets[search_name] = skills
    return targets


def searchable_learning_targets(points: dict[str, dict], search_names: dict[str, str]) -> dict[str, list[str]]:
    """Preserve confirmed concepts verbatim under each exact search name.

    These remain requirements with unknown coverage until source evidence is
    obtained. No API alias, project background or additional target is inferred.
    """
    observed, targets = {}, {}
    for point_id, search_name in search_names.items():
        concepts = list(points[point_id].get("concepts") or [])
        if search_name in observed and observed[search_name] != concepts:
            raise SearchTargetCollision("Distinct learning units share a search name but have different confirmed concepts")
        observed[search_name] = concepts
        if concepts:
            targets[search_name] = concepts
    return targets


def searchable_unit_name(point: dict, technical_plan: str = "") -> str:
    """Add an unambiguous observed API owner, without shortening the unit.

    Explicit unit technology defines the leading retrieval owner without
    rewriting the editable title or concepts. Qualified namespaces in the unit's own concepts are sufficient; short Pygame API names
    also require the confirmed plan to choose Pygame. Game-specific state units
    may inherit it only from a single unambiguous game framework in that plan.
    Historic units without concepts keep their original text.
    """
    name = canonical_search_name(point["name"])
    if len(name) > 160:
        raise ValueError("The canonical unit search name exceeds the search target limit")
    technology = " ".join((point.get("technology") or "").split())
    if technology and technology.casefold() not in {"通用", "无", "general", "none", "not_applicable"}:
        # A tool mentioned later in the title is not the retrieval owner.
        # Complete identifiers (including foreign namespaces) stay distinct.
        if (leading_technical_owner(name) or name).casefold() == technology.casefold():
            return name
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.+#-]*", technology) and re.match(
                re.escape(technology) + r"(?![A-Za-z0-9_])", name, re.I):
            return name  # Preserve the existing explicit multi-tool contract.
        enriched = technology + " " + name
        if len(enriched) > 160:
            raise ValueError("The unit name and technology exceed the search target limit")
        return enriched
    if _COMPETING.search(name):
        return name
    concepts = re.sub(r"https?://\S+", "", "\n".join(point.get("concepts") or []), flags=re.I)
    owners = {owner for owner in _NAMESPACES
              if re.search(r"(?<![A-Za-z0-9_])" + owner + r"\.[A-Za-z_]", concepts, re.I)}
    if (not owners and re.search(r"(?<![A-Za-z0-9_])pygame(?![A-Za-z0-9_])", technical_plan, re.I)
            and _PYGAME_API.search(concepts)):
        owners.add("pygame")
    plan_tools = {match.group().lower() for match in _COMPETING.finditer(technical_plan)}
    if (not owners and plan_tools == {"pygame"}
            and re.search(r"游戏|挡板|小球|漏接|计分|空格.{0,3}重开", name)):
        owners.add("pygame")
    if len(owners) != 1:
        return name  # Ambiguous multi-tool units need an explicit title.
    enriched = next(iter(owners)) + " " + name
    return enriched if len(enriched) <= 160 else name  # Never truncate a student target.
