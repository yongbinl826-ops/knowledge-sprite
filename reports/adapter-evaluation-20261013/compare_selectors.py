"""Offline selector-only comparison; input identity comes exclusively from sample-manifest.json."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ATTEMPTS = []


def no_network_or_child_process(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "subprocess.Popen", "os.system", "os.spawn"}:
        ATTEMPTS.append({"event": event})
        raise RuntimeError("Offline comparison forbids network and child processes")


sys.addaudithook(no_network_or_child_process)
# No fetcher, browser, application module, or external URL loader is imported.
from bs4 import BeautifulSoup
from scrapling.parser import Selector


CONTRACT = [
    ("document_title", "title", None),
    ("meta_title", 'meta[property="og:title"]', "content"),
    ("meta_description", 'meta[name="description"]', "content"),
    ("meta_og_description", 'meta[property="og:description"]', "content"),
    ("html_language", "html", "lang"),
    ("mit_course_heading", "#course-banner h1", None),
    ("mit_course_instructor_names", ".course-info-instructor", None),
    ("mit_chapter_description", ".video-page .description", None),
    ("mit_catalog_titles", "main#course-content-section .video-gallery-card .video-title", None),
    ("mit_catalog_hrefs", "main#course-content-section .video-gallery-card a.video-link[href]", "href"),
    ("archive_player_args", "play-av[args][playlist]", "args"),
    ("archive_playlist", "play-av[args][playlist]", "playlist"),
]


def normal_text(value):
    return " ".join(value.split())


def extract(html, url, parser):
    if parser == "beautifulsoup":
        page = BeautifulSoup(html, "html.parser")
        select = page.select
        text = lambda node: normal_text(node.get_text(" ", strip=True))
        attribute = lambda node, key: node.attrs.get(key)
    else:
        page = Selector(content=html, url=url, encoding="utf-8", huge_tree=False, adaptive=False)
        select = page.css
        text = lambda node: normal_text(" ".join(str(value) for value in node.xpath(".//text()").getall()))
        attribute = lambda node, key: node.attrib.get(key)
    output = {}
    for field, css, attr in CONTRACT:
        output[field] = [str(attribute(node, attr)) if attribute(node, attr) is not None else None
                         for node in select(css)] if attr else [text(node) for node in select(css)]
    # Same standard-library JSON interpretation on both parsers' actual attribute.
    output["archive_playlist_titles"] = [[entry.get("title") for entry in json.loads(value)]
                                          for value in output["archive_playlist"]]
    return output


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def main():
    manifest_path = HERE / "sample-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    documents = manifest["documents"]
    if len(documents) != 4:
        raise RuntimeError("Expected exactly four frozen documents")
    payloads = []
    for document in documents:
        path = (ROOT / document["file"]).resolve()
        if not path.is_relative_to(ROOT):
            raise RuntimeError("Manifest input is outside workspace")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != document["sha256"] or len(data) != document["bytes"]:
            raise RuntimeError("Frozen input identity mismatch: " + document["file"])
        payloads.append((document, data.decode("utf-8")))
    versions = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions() if dist.metadata["Name"]}
    if versions.get("scrapling") != "0.4.15" or versions.get("beautifulsoup4") != "4.15.0":
        raise RuntimeError("Comparison package versions do not match the protocol")
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scope": "offline parser/selector comparison only, not fetch success or course coverage",
        "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "dependencies": dict(sorted(versions.items())),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_count": manifest["sources"], "course_family_count": manifest["reviewed_course_families"],
        "warmups_per_parser_per_document": 1, "timed_repeats": 7,
        "timing_scope": "new DOM parse plus identical field selection and playlist JSON decoding; excludes imports, disk reading and input hashing",
        "contract": [{"field": field, "css": css, "attribute": attr, "text_normalization": "collapse whitespace" if not attr else None} for field, css, attr in CONTRACT],
        "parser_configuration": {"beautifulsoup": {"parser": "html.parser"}, "scrapling": {"adaptive": False, "huge_tree": False, "encoding": "utf-8"}},
        "network_control": "No URL loaders or fetchers invoked; Python socket/DNS/subprocess audit events forbidden. This is not an OS egress sandbox or a transport-equivalence test.",
        "documents": [],
    }
    for document, html in payloads:
        runs = {name: {"times_ms": [], "output_hashes": []} for name in ("beautifulsoup", "scrapling")}
        outputs = {name: extract(html, document["url"], name) for name in runs}
        for index in range(7):
            order = ("beautifulsoup", "scrapling") if index % 2 == 0 else ("scrapling", "beautifulsoup")
            for name in order:
                started = time.perf_counter_ns()
                output = extract(html, document["url"], name)
                runs[name]["times_ms"].append(round((time.perf_counter_ns() - started) / 1_000_000, 6))
                runs[name]["output_hashes"].append(digest(output))
        for name, run in runs.items():
            run.update(median_ms=statistics.median(run["times_ms"]), min_ms=min(run["times_ms"]), max_ms=max(run["times_ms"]),
                       repeat_outputs_stable=all(value == digest(outputs[name]) for value in run["output_hashes"]))
        differences = [field for field in outputs["beautifulsoup"] if outputs["beautifulsoup"][field] != outputs["scrapling"][field]]
        report["documents"].append({"file": document["file"], "url": document["url"], "role": document["document_role"],
            "sha256": document["sha256"], "bytes": document["bytes"], "hash_verified": True, "equivalent": not differences,
            "different_fields": differences, "measurements": runs, "outputs": outputs,
            "field_counts": {name: {key: len(value) for key, value in output.items()} for name, output in outputs.items()}})
    report["network_attempts"] = ATTEMPTS
    report["all_equivalent"] = all(document["equivalent"] for document in report["documents"])
    report["all_repeats_stable"] = all(run["repeat_outputs_stable"] for doc in report["documents"] for run in doc["measurements"].values())
    report["new_nonempty_fields"] = sum(bool(doc["outputs"]["scrapling"][field]) and not bool(doc["outputs"]["beautifulsoup"][field])
        for doc in report["documents"] for field in doc["outputs"]["beautifulsoup"])
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (HERE / "selector-comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "selector-installed-versions.txt").write_text("\n".join(name + "==" + version for name, version in sorted(versions.items())) + "\n", encoding="utf-8")
    print(json.dumps({"documents": len(report["documents"]), "all_equivalent": report["all_equivalent"],
        "all_repeats_stable": report["all_repeats_stable"], "new_nonempty_fields": report["new_nonempty_fields"], "network_attempts": ATTEMPTS}, ensure_ascii=True))
    if ATTEMPTS or not report["all_equivalent"] or not report["all_repeats_stable"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
