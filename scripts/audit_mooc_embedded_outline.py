"""Compare the extractor to the current saved HTTP body; no network requests."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from backend.app.extractor import MetadataExtractor


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/mooc-public-read-20261017"
BODY = OUT / "direct-probe/02-page.body"
URL = "https://www.icourse163.org/course/PKU-1003479006"


def main():
    raw = BODY.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "c492d76ac452b0189057e6d061470b434d14189a6e38931a91a9f2adebf04af4"
    text = raw.decode("utf-8")
    # This independent, exact-field comparison is deliberately not the production
    # parser. It only audits the one immutable real response named above.
    values = re.findall(r'\boutLine\s*:\s*("(?:\\.|[^"\\])*")', text)
    assert len(values) == 1
    literal_html = json.loads(values[0])
    paragraphs = BeautifulSoup(literal_html, "html.parser").select("p")
    expected_titles = [" ".join(p.get_text(" ", strip=True).split()) for p in paragraphs if p.get_text(strip=True)]
    extracted = MetadataExtractor().extract(text, URL, "offline-analysis-of-current-http-response")
    assert expected_titles == [row["title"] for row in extracted["chapters"]]
    soup = BeautifulSoup(text, "html.parser")
    report = {
        "activity": "offline_static_analysis_of_current_http_capture",
        "network_requests_by_this_script": 0,
        "source": str(BODY.relative_to(ROOT)).replace("\\", "/"),
        "source_url": URL,
        "source_bytes": len(raw),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "visible_outline_target_empty": not bool(soup.select_one("#j-course-outline").get_text(strip=True)),
        "observed_embedded_path": "window.termDto.outLineDto.outLine",
        "observed_course_id": "1003479006",
        "observed_term_id": "1476734461",
        "public_literal_html_sha256": hashlib.sha256(literal_html.encode()).hexdigest(),
        "independent_paragraph_count": len(expected_titles),
        "extractor_chapter_count": len(extracted["chapters"]),
        "ordered_titles_identical": True,
        "lesson_labels": sum(bool(re.match(r"课程\d+", title)) for title in expected_titles),
        "chapter_labels": sum(bool(re.match(r"[一二三四五六七八九十]+、", title)) for title in expected_titles),
        "tutorial_labels": sum(title.startswith("视频教程：") for title in expected_titles),
        "quiz_and_assignment_labels": sum(title.startswith("章节") for title in expected_titles),
        "entries_with_explicit_duration": sum(row["duration_seconds"] is not None for row in extracted["chapters"]),
        "catalog_kind": extracted["catalog_kind"],
        "field_provenance": extracted["field_provenance"],
        "ordered_titles": expected_titles,
        "boundaries": {"scripts_executed": False, "extra_api_requests": 0, "media_requests": 0,
                       "playback_verified": False, "lesson_urls": "unknown", "access_requirements": "unknown",
                       "closed_term_notice": "unknown; numeric flags not interpreted"},
        "source_code_hashes": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in [ROOT / "backend/app/source_adapters/icourse163.py", ROOT / "backend/app/extractor.py"]},
    }
    (OUT / "embedded-outline-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"catalog_entries": len(expected_titles), "ordered_titles_identical": True,
                      "report": str(OUT / "embedded-outline-analysis.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
