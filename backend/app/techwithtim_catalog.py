"""Bounded Tech With Tim public HTML category -> series -> observed lesson links.

Category routes describe the site's observed public taxonomy, never video IDs
or project answers. Directory text only chooses probes; detail identity and
teaching evidence remain mandatory and independent in the existing pipeline.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .extractor import detect_access_page
from .fetcher import FetchStopped, NETWORK_OBSERVER, utcnow
from .models import Candidate
from .providers import SearchBudgetReached, SearchError
from .public_catalog import PublicCatalogProvider, MAX_INDEX_BYTES, MAX_TOTAL_BYTES
from .url_utils import UnsafeURL, normalize_url


ORIGIN = "https://www.techwithtim.net"
VERSION = 1
RECALL_VERSION = 3
MAX_SERIES = 2
MAX_INDEXES = 1 + MAX_SERIES
# Observed category-card destinations in /tutorials. No series/lesson seed URLs.
CATEGORIES = {"pygame": "game-development-with-python", "python": "python-programming",
    "java": "java-programming", "django": "django", "flask": "flask", "discord.py": "discord-py",
    "tensorflow": "machine-learning-python", "numpy": "python-module-walk-throughs", "kivy": "python-module-walk-throughs"}


def scoped_url(value, base=None, *, depth=None):
    try:
        raw = urljoin(base, value) if base else value
        parts = urlsplit(raw)
        # Reject even tracking queries before generic normalization drops them.
        if parts.query or parts.fragment:
            return None
        url = normalize_url(raw)
        parts = urlsplit(url)
        components = parts.path.strip("/").split("/")
        if (parts.scheme != "https" or parts.hostname != "www.techwithtim.net" or parts.port not in (None, 443)
                or not 1 <= len(components) <= 4 or components[0] != "tutorials"
                or any(not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", component) for component in components)
                or (depth is not None and len(components) != depth)):
            return None
        return ORIGIN + "/" + "/".join(components)
    except (UnsafeURL, ValueError, TypeError):
        return None


def catalog_url(value, base=None):
    url = scoped_url(value, base)
    return url if url and len(urlsplit(url).path.strip("/").split("/")) <= 3 else None


def lesson_url(value, base=None):
    return scoped_url(value, base, depth=4)


def parse_catalog(body: bytes, source_url: str) -> dict:
    source = catalog_url(source_url)
    if source is None or len(body) > MAX_INDEX_BYTES or b"\x00" in body:
        raise SearchError("invalid_response", "Public lesson directory exceeded its HTML/scope boundary.")
    soup = BeautifulSoup(body, "html.parser")
    access = detect_access_page(soup, source)
    if access in {"captcha", "access_denied", "login_required"}:
        raise FetchStopped(access, "Public lesson directory shows an access restriction.")
    depth = len(urlsplit(source).path.strip("/").split("/"))
    cards, lessons, seen = [], [], set()
    if depth <= 2:
        for card in soup.select("div[class*='tutorial__TutorialCardContainer']")[:60]:
            heading = card.select_one("h3[class*='TutorialCardTitle']")
            description = card.select_one("p[class*='TutorialCardDescription']")
            if heading is None:
                continue
            for anchor in card.select("a[href]")[:10]:
                target = scoped_url(str(anchor.get("href", "")), source, depth=depth + 1)
                if not target or not target.startswith(source + "/") or target in seen:
                    continue
                title = " ".join(heading.get_text(" ", strip=True).split())[:600]
                if title:
                    cards.append({"url": target, "title": title,
                                  "snippet": " ".join(description.get_text(" ", strip=True).split())[:1600] if description else ""})
                    seen.add(target)
                    break
    elif depth == 3:
        for box in soup.select("div[class*='tutoriallayout__Lessons-']")[:2]:
            for anchor in box.select("a[href]")[:80]:
                target = lesson_url(str(anchor.get("href", "")), source)
                title = " ".join(anchor.get_text(" ", strip=True).split())[:600]
                if target and target.startswith(source + "/") and target not in seen and title:
                    lessons.append({"url": target, "title": title, "snippet": ""})
                    seen.add(target)
    return {"source_url": source_url, "source_sha256": hashlib.sha256(body).hexdigest(), "observed_at": utcnow(),
            "cache_hit": False, "cards": cards, "lessons": lessons, "kind": "series" if depth == 3 else "category"}


def recall_terms(text):
    """Small grammatical variants affect ordering only, never topic evidence."""
    terms = set(re.findall(r"[a-z][a-z0-9_.+#-]*", text.casefold())) - {"video", "videos", "course", "tutorial", "lesson", "learn", "with", "and", "the", "for", "of", "to"}
    for token in list(terms):
        if len(token) > 5 and token.endswith("ing"):
            terms.update((token[:-3], token[:-3] + "e"))
        elif len(token) > 5 and token.endswith("ment"):
            terms.add(token[:-4])
        elif len(token) > 4 and token.endswith("s"):
            terms.add(token[:-1])
    return terms


def lesson_recall_plan(query, original_point, learning_targets=None):
    """A bounded directory-heading hint plan, never a claim that skills are taught.

    Lesson headings often describe the output (a score/health display) rather
    than its rendering API. Only explicit pygame font/text-display intent can
    expand to those headings. No URL, lesson ID or project answer is used.
    """
    hints = [str(query)[:1200], str(original_point or "")[:400]]
    targets = ([value[:240] for value in learning_targets[:24] if isinstance(value, str)]
               if isinstance(learning_targets, (list, tuple)) else [])
    hints.extend(targets)
    owner = re.match(r"\s*([A-Za-z][A-Za-z0-9+#._-]{1,40})(?![A-Za-z0-9_])", original_point or query)
    tool = owner[1] if owner else ""
    literal = recall_terms(" ".join(hints)) - recall_terms(tool)
    heading, rules = set(), []
    if tool.casefold() == "pygame":
        font_api = re.compile(r"(?<![A-Za-z0-9_.])pygame\.font(?:\.[A-Za-z_][A-Za-z0-9_]*)?(?![A-Za-z0-9_.])", re.I)
        display = re.compile(r"(?<![A-Za-z0-9_.])font(?![A-Za-z0-9_.])|"
            r"(?<![A-Za-z0-9_.])(?:render|display|draw)(?:ing)?\s+text\b|"
            r"\btext\s+(?:rendering|display|drawing)\b|字体|(?:渲染|显示|绘制)(?:文字|文本)|(?:文字|文本)(?:渲染|显示|绘制)", re.I)
        foreign = re.compile(r"(?<![A-Za-z0-9_.])(?:matplotlib|pandas|tkinter|pillow|opencv|unity|godot)(?![A-Za-z0-9_.])", re.I)
        if any(font_api.search(text) or (not foreign.search(text) and display.search(text)) for text in hints):
            heading = recall_terms("scoring health")
            rules.append("pygame_font_text_display_to_score_health_heading")
    return {"recall_version": RECALL_VERSION, "literal_terms": sorted(literal), "heading_hint_terms": sorted(heading), "rules": rules,
            "confirmed_target_count": len(targets),
            "confirmed_targets_sha256": hashlib.sha256(json.dumps(targets, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}


def order_observed_lessons(lessons, plan):
    """Rank only titles actually read from this series; stable source-order ties."""
    wanted, hints = set(plan["literal_terms"]), set(plan["heading_hint_terms"])
    return sorted(enumerate(lessons), key=lambda row: (
        -len(wanted & recall_terms(row[1]["title"])),
        -len(hints & recall_terms(row[1]["title"])), row[0]))


def series_probe_order(cards, plan):
    """At most two observed series; no URL words or lesson-answer seeds.

    A positive category overlap keeps the next best observed card as fallback.
    With no category signal, sample separated source positions rather than
    always the first adjacent cards. This is finite directory diversity only.
    """
    wanted = set(plan["literal_terms"])
    choices = sorted(enumerate(cards), key=lambda row: (
        -len(wanted & recall_terms(row[1]["title"] + " " + row[1]["snippet"])), row[0]))
    if len(choices) <= 1:
        return choices
    best = len(wanted & recall_terms(choices[0][1]["title"] + " " + choices[0][1]["snippet"]))
    return [choices[0], choices[1] if best else choices[len(choices) // 2]]


def select_observed_candidates(documents, plan, query, entry, limit):
    """Retain heading order and one candidate per successfully read series."""
    wanted, hints = set(plan["literal_terms"]), set(plan["heading_hint_terms"])
    ranked = []
    for series_index, (card, document) in enumerate(documents):
        for lesson_index, lesson in enumerate(document["lessons"]):
            priority = (-len(wanted & recall_terms(lesson["title"])),
                        -len(hints & recall_terms(lesson["title"])), series_index, lesson_index)
            ranked.append((priority, lesson, card, document, series_index, lesson_index))
    ranked.sort(key=lambda row: row[0])
    if not ranked:
        return []
    cap = min(6, max(0, limit))
    selected, used = [], set()
    # The strongest heading comes first. Another observed series gets one
    # early bounded probe, including when all headings have zero recall signal.
    for item in ranked:
        if item[4] not in used:
            selected.append(item)
            used.add(item[4])
        if len(selected) >= min(cap, len({row[4] for row in ranked})):
            break
    for item in ranked:
        if len(selected) >= cap:
            break
        if item not in selected:
            selected.append(item)
    results, seen = [], set()
    for _, lesson, card, document, series_index, lesson_index in selected[:cap]:
        if lesson["url"] in seen:
            continue
        seen.add(lesson["url"])
        results.append(Candidate(id=hashlib.sha256(("techwithtim_catalog\0" + query + "\0" + lesson["url"]).encode()).hexdigest()[:24],
            title=lesson["title"], url=lesson["url"], snippet=lesson["snippet"], source="techwithtim_catalog", query=query,
            discovery_evidence={"kind": "public_catalog_link", "source_url": document["source_url"], "source_sha256": document["source_sha256"],
                "observed_at": document["observed_at"], "cache_hit": document["cache_hit"], "observed_url": lesson["url"],
                "parent_category_url": entry, "parent_series_url": card["url"], "parent_series_title": card["title"],
                "confidence": "low", "independent_detail_required": True,
                "recall_rules": plan["rules"], "confirmed_targets_sha256": plan["confirmed_targets_sha256"],
                "literal_heading_matches": sorted(wanted & recall_terms(lesson["title"])),
                "heading_hint_matches": sorted(hints & recall_terms(lesson["title"])),
                "provider_result_index": len(results), "series_index": series_index, "lesson_source_index": lesson_index}))
    return results


class TechWithTimCatalogProvider(PublicCatalogProvider):
    name = "techwithtim_catalog"
    cache_identity = "techwithtim-observed-category-series-lessons-v1"

    @staticmethod
    def supports(original_point: str) -> bool:
        match = re.match(r"\s*([A-Za-z][A-Za-z0-9+#._-]{1,40})(?![A-Za-z0-9_])", original_point)
        return bool(match and match[1].casefold() in CATEGORIES)

    def _key(self, url):
        fields = {"url": url, "version": VERSION, "parser": self.cache_identity, "ttl": self.settings.search_cache_ttl,
                  "enabled": self.settings.fetch_enabled, "dns": self.settings.dns_resolver,
                  "denied": self.settings.denied_fetch_hosts, "allowed": self.settings.allowed_restricted_hosts}
        return self.store.cache_key(self.name, fields) if self.store else hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()

    def _put(self, url, value):
        ttl = self.settings.search_cache_ttl
        if ttl <= 0:
            return
        key = self._key(url)
        if self.store:
            self.store.cache_set(key, self.name, value, ttl)
        else:
            if len(self.memory_cache) >= 32:
                self.memory_cache.pop(next(iter(self.memory_cache)))
            self.memory_cache[key] = (time.monotonic() + ttl, deepcopy(value))

    async def _before_resolve(self, url):
        if url != ORIGIN + "/robots.txt" and catalog_url(url) not in self._allowed_urls:
            raise FetchStopped("scope_blocked", "Only the selected public category and its observed series may be read.")
        if self.budget_check_hook:
            await self.budget_check_hook()

    async def _document(self, url):
        document = self._get(url)
        if document is None:
            response = await self.fetcher.fetch(url)
            if response.status_code in {401, 403, 429}:
                raise SearchError("access_denied", "The public directory denied access; no alternate route used.")
            if response.status_code != 200:
                raise SearchError("search_unavailable", "The public directory did not return an available page.")
            if not any(value in response.headers.get("content-type", "").lower() for value in ("text/html", "application/xhtml+xml")):
                raise SearchError("invalid_response", "The public directory did not return HTML.")
            document = parse_catalog(response.body, response.url)
            self._put(url, document)
        self.last_discovery["indexes"].append({key: value for key, value in document.items() if key not in {"cards", "lessons"}} |
            {"observed_card_count": len(document["cards"]), "observed_lesson_count": len(document["lessons"])})
        return document

    async def search(self, query: str, language: str, limit: int, domain_filters: list[str], *,
                     original_point: str | None = None, technical_version: str = "",
                     learning_targets: list[str] | None = None) -> list[Candidate]:
        self.last_requests, self.last_dns_requests, self.last_warnings = [], [], []
        self._total_bytes, self._last_rate_limit_delay = 0, None
        self.last_discovery = {"scope": "public category then at most two observed series; lesson links require independent detail", "indexes": [],
                               "max_indexes": MAX_INDEXES, "max_series": MAX_SERIES}
        if domain_filters and not any(ORIGIN.split("//")[1] == d or ORIGIN.split("//")[1].endswith("." + d) for d in domain_filters):
            return []
        if not self.settings.fetch_enabled or limit <= 0:
            return []
        if self._hard_stopped or self._cooldown_until > time.monotonic():
            self.last_status = "fault"
            self.last_discovery.update(source_stopped=True, stop_reason=self._hard_stopped or "rate_limited")
            raise SearchError("access_denied", "The public lesson source is stopped or cooling down; no request made.")
        tool_match = re.match(r"\s*([A-Za-z][A-Za-z0-9+#._-]{1,40})(?![A-Za-z0-9_])", original_point or query)
        category = CATEGORIES.get(tool_match[1].casefold()) if tool_match else None
        if not category:
            self.last_discovery["unsupported_explicit_tool"] = True
            return []
        tool = tool_match[1]
        entry = ORIGIN + "/tutorials/" + category
        self._allowed_urls = {entry}
        token = NETWORK_OBSERVER.set({"before_resolve": self._before_resolve, "before_target_http": self._target_count,
            "before_dns_http": self._dns_count, "target_trace": self._trace, "dns_trace": self.last_dns_requests.append,
            "response": self._capture, "response_byte_limit": lambda: min(MAX_INDEX_BYTES, MAX_TOTAL_BYTES - self._total_bytes), "max_retries": 0})
        documents = []
        recall = None
        try:
            first = await self._document(entry)
            recall = lesson_recall_plan(query, original_point or query, learning_targets)
            wanted = set(recall["literal_terms"])
            self.last_discovery["recall_plan"] = recall
            choices = series_probe_order(first["cards"], recall)
            if not choices:
                self.last_status = "available"
                return []
            self.last_discovery["series_selection_policy"] = "category literal recall; separated source positions on a zero-signal tie; second series only after no lesson heading signal"
            for _, selected in choices[:MAX_SERIES]:
                self._allowed_urls.add(selected["url"])
                try:
                    series = await self._document(selected["url"])
                except (SearchBudgetReached, SearchError, FetchStopped) as exc:
                    self.last_discovery["failed_index"] = {"source_url": selected["url"],
                        "status": "budget_stopped" if isinstance(exc, SearchBudgetReached) else
                                  exc.status if isinstance(exc, FetchStopped) else exc.code}
                    raise
                documents.append((selected, series))
                if any((wanted | set(recall["heading_hint_terms"])) & recall_terms(row["title"]) for row in series["lessons"]):
                    break
            self.last_discovery["heading_match_count"] = sum(bool((wanted | set(recall["heading_hint_terms"])) & recall_terms(row["title"])) for _, series in documents for row in series["lessons"])
            self.last_discovery["heading_order_policy"] = "strongest actual heading first; one early candidate per observed series; then heading/source order; no teaching proof"
            results = select_observed_candidates(documents, recall, query, entry, limit)
            self.last_status = "available"
            self.last_discovery["candidate_count"] = len(results)
            return results
        except SearchBudgetReached as exc:
            if recall:
                exc.partial_candidates = select_observed_candidates(documents, recall, query, entry, limit)
            self.last_discovery["budget_stopped"] = True
            raise  # A category/series URL is never substituted as a video.
        except FetchStopped as exc:
            self.last_status = "fault"
            restricted = {"robots_blocked", "site_policy_blocked", "access_denied", "rate_limited", "captcha", "login_required"}
            if exc.status == "rate_limited":
                if self._last_rate_limit_delay is None:
                    self._cooldown_until = max(self._cooldown_until, time.monotonic() + 60)
            elif exc.status in restricted:
                self._hard_stopped = exc.status
            if exc.status in restricted:
                self.last_discovery.update(source_stopped=True, stop_reason=exc.status)
            elif documents and recall:
                self.last_warnings.append({"code": "search_unavailable", "message": "Later bounded public series lookup failed; retained only earlier observed lesson links."})
                return select_observed_candidates(documents, recall, query, entry, limit)
            raise SearchError("access_denied" if exc.status in restricted else "search_unavailable", "Public directory access failed or stopped; no hidden API or route workaround used.") from None
        except SearchError as exc:
            self.last_status = "fault"
            if exc.code == "access_denied":
                self._hard_stopped = "http_access_denied"
                self.last_discovery.update(source_stopped=True, stop_reason=self._hard_stopped)
            elif documents and recall:
                self.last_warnings.append({"code": exc.code, "message": "Later bounded public series lookup failed; retained only earlier observed lesson links."})
                return select_observed_candidates(documents, recall, query, entry, limit)
            raise
        finally:
            NETWORK_OBSERVER.reset(token)
