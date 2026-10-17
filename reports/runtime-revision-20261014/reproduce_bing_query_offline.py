"""Read public installed source; reconstruct URLs offline. Never sends HTTP."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlencode, urlparse

HERE = Path(__file__).resolve().parent
CONTAINER = "knowledge-sprite-searxng-1"
SOURCES = {
    "bing.py": "/usr/local/searxng/searx/engines/bing.py",
    "query.py": "/usr/local/searxng/searx/query.py",
    "webadapter.py": "/usr/local/searxng/searx/webadapter.py",
    "search.py": "/usr/local/searxng/searx/search/__init__.py",
    "online.py": "/usr/local/searxng/searx/search/processors/online.py",
    "network.py": "/usr/local/searxng/searx/network/network.py",
    "client.py": "/usr/local/searxng/searx/network/client.py",
    "curl_utils.py": "/usr/local/searxng/.venv/lib/python3.14/site-packages/curl_cffi/requests/utils.py",
}


def selected_nodes(text, names):
    return ast.Module(body=[n for n in ast.parse(text).body
        if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names], type_ignores=[])


def main():
    source_dir = HERE / "bing-readonly-sources"
    source_dir.mkdir(exist_ok=True)
    texts, hashes = {}, {}
    for name, path in SOURCES.items():
        data = subprocess.run(["docker", "exec", CONTAINER, "cat", path],
            check=True, capture_output=True).stdout
        texts[name] = data.decode("utf-8")
        hashes[path] = hashlib.sha256(data).hexdigest()
        (source_dir / name).write_bytes(data)

    # Execute only explicitly selected pure parser/request-builder definitions.
    # No SearXNG module imports, app initialization, preferences, env or settings.
    namespace = {"re": re, "ABC": ABC, "abstractmethod": abstractmethod}
    names = {"QueryPartParser", "TimeoutParser", "LanguageParser", "ExternalBangParser",
             "BangParser", "FeelingLuckyParser", "RawTextQuery"}
    exec(compile(selected_nodes(texts["query.py"], names), "query.py", "exec"), namespace)
    builder = {"traits": SimpleNamespace(get_region=lambda *_: "en-us", all_locale="clear"),
        "base_url": "https://www.bing.com", "urlencode": urlencode,
        "_safesearch_map": {0: "off", 1: "moderate", 2: "strict"}}
    exec(compile(selected_nodes(texts["bing.py"], {"request"}), "bing.py", "exec"), builder)
    quoter = {"quote": quote, "InvalidURL": ValueError,
        "UNRESERVED_SET": frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")}
    exec(compile(selected_nodes(texts["curl_utils.py"], {"unquote_unreserved", "requote_uri"}),
        "curl_utils.py", "exec"), quoter)

    rows, report_hashes = [], {}
    for report_file, source_name in [("dynamic-live.json", "dynamic-sources"),
                                     ("dynamic-course-id-live.json", "dynamic-course-id-sources")]:
        report_data = (HERE / report_file).read_bytes()
        report_hashes[report_file] = hashlib.sha256(report_data).hexdigest()
        report = json.loads(report_data)
        for item in report["search_http"]:
            query = parse_qs(urlparse(item["url"]).query)["q"][0]
            parsed = namespace["RawTextQuery"](query, []).getQuery()
            params = {"searxng_locale": "en", "safesearch": 0}
            builder["request"](parsed, params)
            final_url = quoter["requote_uri"](params["url"])
            raw_bytes = (HERE / source_name / item["file"]).read_bytes()
            body = json.loads(raw_bytes)
            row = {"report": report_file, "response_file": f"{source_name}/{item['file']}",
                "recorded_loopback_url": item["url"], "recorded_status": item["status"],
                "recorded_response_sha256_matches": hashlib.sha256(raw_bytes).hexdigest() == item["sha256"],
                "input_query": query, "raw_text_query_output": parsed,
                "searxng_response_query": body.get("query"), "reconstructed_bing_url": final_url,
                "decoded_bing_q": parse_qs(urlparse(final_url).query)["q"][0],
                "preserves_all_terms": parsed == " ".join(query.split()) and
                    parse_qs(urlparse(final_url).query)["q"][0] == parsed,
                "result_urls": [r["url"] for r in body["results"]],
                "unresponsive_engines": body.get("unresponsive_engines"),
                "response_result_count": len(body["results"])}
            assert row["preserves_all_terms"] and row["recorded_response_sha256_matches"]
            assert body["query"] == parsed
            rows.append(row)
    result = {"created_at": datetime.now(timezone.utc).isoformat(),
        "method": "offline AST of public container parser, Bing request builder and curl_cffi URI quoting; no module initialization or network",
        "container": CONTAINER, "container_image": "ghcr.io/searxng/searxng@sha256:ddd642cae6eac75412938fd846ddbf440a2df029cfeae8a562b8b205f4e35e25",
        "curl_cffi_version": "0.16.3", "source_sha256": hashes, "existing_report_sha256": report_hashes,
        "locale_and_safesearch": "reconstruction fixture en-us/off, not read from runtime preferences; q is unaffected",
        "requests_sent": 0, "rows": rows,
        "all_checks_passed": all(r["preserves_all_terms"] and r["recorded_response_sha256_matches"] for r in rows),
        "within_group_result_urls_identical": all(rows[i]["result_urls"] == rows[i+1]["result_urls"] == rows[i+2]["result_urls"] for i in (0, 3)),
        "unknown": ["actual historical outbound Bing URL after runtime plugins and redirects",
            "historical raw Bing HTML and rewritten query", "upstream routing/cache/localization or search relevance behavior"]}
    (HERE / "bing-query-readonly-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checks": len(rows), "all_checks_passed": result["all_checks_passed"],
        "within_group_result_urls_identical": result["within_group_result_urls_identical"], "requests_sent": 0}))


if __name__ == "__main__":
    main()
