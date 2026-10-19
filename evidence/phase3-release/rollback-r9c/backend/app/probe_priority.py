"""Discovery-only priority inside an already-admitted, bounded probe queue.

No teaching claim, URL seed, model call, or additional request is introduced.
The caller retains its current owner/type/video checks and quota accounting.
"""
from __future__ import annotations

import re

_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*(?:[.-][A-Za-z_][A-Za-z0-9_]*)*)(\s*\()?"
)


def _target_identifiers(targets):
    found = set()
    for target in targets[:8]:
        if not isinstance(target, str):
            continue
        for match in _IDENTIFIER.finditer(target[:120]):
            name, call = match.groups()
            # Do not treat ordinary prose or acronyms (CSV/HTML) as an API.
            if ("." in name or "_" in name or "-" in name or call
                    or re.search(r"[a-z][A-Z]", name)):
                if len(name.rsplit(".", 1)[-1]) >= 3:
                    found.add(name.casefold())
    return found


def has_literal_identifier(value):
    """Recognize spelling shape, without an API vocabulary or teaching claim."""
    return isinstance(value, str) and bool(_target_identifiers([value]))


def probe_api_priority(point, evidence, *, owner, owner_gate_passed):
    """Return a stable two-part discovery hint, never a coverage status.

    Full literal identifiers rank before same operation-name spelling under
    the explicitly selected tool. The latter is an operation-name recall hint,
    not an asserted alias equivalence. Foreign qualified namespaces cannot
    borrow a tool name elsewhere in the title. Query/snippet/body are ignored.
    """
    if not owner_gate_passed or not isinstance(owner, str) or not owner.strip():
        return (0, 0)
    targets = point.get("learning_targets")
    if not isinstance(targets, list):
        return (0, 0)
    wanted = _target_identifiers(targets)
    if not wanted:
        return (0, 0)
    wanted_leaves = {name.rsplit(".", 1)[-1] for name in wanted}
    exact, operation = set(), set()
    pid = point.get("knowledge_point_id")
    owner = owner.casefold().strip()
    owner_relative = {name[len(owner) + 1:] for name in wanted if name.startswith(owner + ".")}
    for entry in evidence:
        if (entry.get("kind") != "search"
                or entry.get("knowledge_point_id") != pid
                or entry.get("source") in {"public_catalog", "techwithtim_catalog", "official_sitemap"}
                or not isinstance(entry.get("title"), str)):
            continue
        for match in _IDENTIFIER.finditer(entry["title"][:1000]):
            name = match[1].casefold()
            if name in wanted:
                exact.add(name)
            elif name in owner_relative:
                # The explicitly selected owner may be printed separately;
                # retain the remaining namespace path exactly, without aliases.
                operation.add(name)
            elif name.rsplit(".", 1)[-1] in wanted_leaves:
                if "." not in name or name.split(".", 1)[0] == owner:
                    operation.add(name.rsplit(".", 1)[-1])
    return (len(exact), len(operation))
