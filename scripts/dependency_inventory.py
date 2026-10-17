"""Record resolved dependency versions and package-supplied license metadata."""
import importlib.metadata
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
entries = []
for package in importlib.metadata.distributions():
    meta = package.metadata
    entries.append({"ecosystem": "python", "name": meta.get("Name"), "version": package.version,
                    "license": meta.get("License-Expression") or meta.get("License") or "unknown",
                    "license_classifiers": [x for x in meta.get_all("Classifier", []) if x.startswith("License ::")],
                    "project_urls": meta.get_all("Project-URL", [])})
lockpath = root / "frontend/package-lock.json"
if lockpath.exists():
    for name, meta in json.loads(lockpath.read_text(encoding="utf-8"))["packages"].items():
        if name:
            entries.append({"ecosystem": "npm", "name": name.removeprefix("node_modules/"),
                            "version": meta.get("version"), "license": meta.get("license", "unknown"),
                            "resolved": meta.get("resolved"), "integrity": meta.get("integrity")})
(root / "reports/dependency-inventory.json").write_text(
    json.dumps(sorted(entries, key=lambda x: (x["ecosystem"], x["name"].lower())), indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Recorded {len(entries)} dependencies; metadata is informational, not a license audit.")
