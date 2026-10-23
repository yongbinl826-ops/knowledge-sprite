#!/usr/bin/env python3
"""Small, standard-library ADB QA helper. All tap targets come from UI XML.

Examples (place common options before the subcommand):
  python adb_qa.py --adb C:/SDK/platform-tools/adb.exe --serial emulator-5554 capture stage-1
  python adb_qa.py --adb C:/SDK/platform-tools/adb.exe --serial emulator-5554 summary
  python adb_qa.py --adb C:/SDK/platform-tools/adb.exe --serial emulator-5554 tap --text '下一步'
  python adb_qa.py --adb C:/SDK/platform-tools/adb.exe --serial emulator-5554 tap --class android.widget.EditText --index 0
  python adb_qa.py --adb C:/SDK/platform-tools/adb.exe --serial emulator-5554 input 'test project'
  python adb_qa.py --adb C:/SDK/platform-tools/adb.exe --serial emulator-5554 swipe --direction up

capture/dump save step files plus latest-ui.xml. tap always obtains a fresh UI
dump first. Ambiguous selectors fail unless an explicit zero-based index is
given. swipe derives its endpoints from a scrollable node in the fresh UI tree.
No coordinate-tap command is exposed. Native input text supports ASCII here;
non-ASCII text fails explicitly instead of silently corrupting it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET


class QAError(RuntimeError):
    pass


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def safe_step(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", value):
        raise QAError("Step must be 1-101 ASCII letters/digits/underscore/dot/hyphen, starting with a letter or digit.")
    return value


def bounds(node: ET.Element) -> tuple[int, int, int, int]:
    value = node.get("bounds", "")
    match = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", value)
    if not match:
        raise QAError(f"Invalid UI-tree bounds: {value!r}")
    x1, y1, x2, y2 = map(int, match.groups())
    if x2 <= x1 or y2 <= y1 or x1 < 0 or y1 < 0:
        raise QAError(f"Empty or off-screen UI-tree bounds: {value!r}")
    return x1, y1, x2, y2


def node_info(node: ET.Element, index: int | None = None) -> dict:
    result = {key: node.get(key, "") for key in (
        "text", "content-desc", "resource-id", "class", "bounds",
        "clickable", "focusable", "focused", "scrollable", "enabled", "checked",
    )}
    if index is not None:
        result["index"] = index
    return result


class ADBQA:
    def __init__(self, adb: str, serial: str, output: Path, timeout: float):
        self.adb, self.serial, self.output, self.timeout = adb, serial, output, timeout
        output.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **fields) -> None:
        with (self.output / "adb-qa.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps({"at": timestamp(), "event": event, "serial": self.serial, **fields}, ensure_ascii=False) + "\n")

    def run(self, *arguments: str) -> bytes:
        command = [self.adb, "-s", self.serial, *arguments]
        self.log("command", argv=command)
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            self.log("command_error", error=str(error))
            raise QAError(f"ADB command could not complete: {error}") from error
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        self.log("command_result", exit_code=result.returncode, stdout_bytes=len(result.stdout), stderr=stderr)
        if stderr:
            print(stderr, file=sys.stderr)
        if result.returncode:
            stdout = result.stdout.decode("utf-8", errors="replace")
            raise QAError(f"ADB returned {result.returncode}: {command!r}\n{stdout}\n{stderr}")
        return result.stdout

    def dump(self, step: str = "dump") -> ET.Element:
        step = safe_step(step)
        raw = self.run("exec-out", "uiautomator", "dump", "/dev/tty")
        text = raw.decode("utf-8", errors="strict")
        start = text.find("<?xml")
        if start < 0:
            start = text.find("<hierarchy")
        end = text.rfind("</hierarchy>")
        (self.output / f"{step}.uiautomator.txt").write_text(text, encoding="utf-8")
        if start < 0 or end < start:
            raise QAError(f"uiautomator did not return XML. See {self.output / (step + '.uiautomator.txt')}")
        xml_text = text[start:end + len("</hierarchy>")]
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as error:
            raise QAError(f"Malformed uiautomator XML: {error}") from error
        for filename in (f"{step}.xml", "latest-ui.xml"):
            (self.output / filename).write_text(xml_text + "\n", encoding="utf-8")
        meta = {"at": timestamp(), "serial": self.serial, "step": step, "xml": str(self.output / f"{step}.xml")}
        (self.output / "latest-ui.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.log("ui_dump", **{key: value for key, value in meta.items() if key not in {"at", "serial"}}, nodes=len(list(root.iter("node"))))
        return root

    def capture(self, step: str) -> None:
        step = safe_step(step)
        # uiautomator waits for idle, so capture after dialog/page transitions.
        root = self.dump(step)
        data = self.run("exec-out", "screencap", "-p")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise QAError("screencap did not return PNG bytes; no image was saved.")
        screenshot = self.output / f"{step}.png"
        screenshot.write_bytes(data)
        self.log("capture", screenshot=str(screenshot), png_bytes=len(data))
        print(json.dumps({"screenshot": str(screenshot), "xml": str(self.output / f"{step}.xml"), "nodes": len(list(root.iter("node")))}, ensure_ascii=False))

    def summary(self, xml_path: Path | None, fresh: bool) -> None:
        if fresh:
            root = self.dump("summary")
        else:
            path = xml_path or self.output / "latest-ui.xml"
            if not path.is_file():
                raise QAError(f"No saved UI tree at {path}; run dump/capture or summary --fresh.")
            root = ET.parse(path).getroot()
        for index, node in enumerate(root.iter("node")):
            if any(node.get(key) for key in ("text", "content-desc", "resource-id")) or any(node.get(key) == "true" for key in ("clickable", "focusable", "scrollable")) or "EditText" in node.get("class", ""):
                print(json.dumps(node_info(node, index), ensure_ascii=False))

    def select(self, root: ET.Element, args: argparse.Namespace, scrollable: bool = False) -> ET.Element:
        selectors = {"text": args.text, "content-desc": args.desc, "resource-id": args.resource_id, "class": args.class_name}
        selectors = {key: value for key, value in selectors.items() if value is not None}
        if not selectors and not scrollable:
            raise QAError("Provide --text, --desc, --resource-id, or --class; selectors are exact and combined with AND.")
        candidates = [node for node in root.iter("node") if all(node.get(key) == value for key, value in selectors.items()) and (not scrollable or node.get("scrollable") == "true")]
        if not candidates:
            raise QAError(f"No UI node matched {selectors!r}" + (" with scrollable=true" if scrollable else "") + ". Inspect the latest summary or scroll and re-dump.")
        if args.index is None and len(candidates) != 1:
            for index, node in enumerate(candidates):
                print(json.dumps(node_info(node, index), ensure_ascii=False), file=sys.stderr)
            raise QAError(f"Ambiguous selector: {len(candidates)} matches. Choose an explicit zero-based --index.")
        index = args.index if args.index is not None else 0
        if index < 0 or index >= len(candidates):
            raise QAError(f"--index {index} outside matching node range 0..{len(candidates) - 1}.")
        selected = candidates[index]
        if selected.get("enabled") == "false":
            raise QAError("Refusing to act on a disabled UI node.")
        bounds(selected)
        return selected

    def tap(self, args: argparse.Namespace) -> None:
        root = self.dump("before-tap")
        node = self.select(root, args)
        x1, y1, x2, y2 = bounds(node)
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        self.log("tap_target", node=node_info(node), x=x, y=y, coordinate_source="fresh_uiautomator_xml")
        self.run("shell", "input", "tap", str(x), str(y))
        print(json.dumps({"tapped": node_info(node), "center": [x, y]}, ensure_ascii=False))

    def input_text(self, text: str) -> None:
        if not text or not text.isascii() or any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise QAError("input requires non-empty printable ASCII. Non-ASCII needs a separate verified input method; nothing was typed.")
        # The remote Android shell parses adb shell arguments. Quote its one text
        # argument with POSIX shell rules, not Windows quoting or interpolation.
        encoded = text.replace("%s", "% s").replace(" ", "%s")
        if "%s" in text:
            raise QAError("Literal %s is not supported by Android input text; nothing was typed.")
        self.run("shell", "input", "text", shlex.quote(encoded))
        print(json.dumps({"input_characters": len(text)}, ensure_ascii=False))

    def swipe(self, args: argparse.Namespace) -> None:
        root = self.dump("before-swipe")
        node = self.select(root, args, scrollable=True)
        x1, y1, x2, y2 = bounds(node)
        width, height = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        if args.direction in ("up", "down"):
            start, end = [cx, y1 + int(height * .75)], [cx, y1 + int(height * .25)]
        else:
            start, end = [x1 + int(width * .75), cy], [x1 + int(width * .25), cy]
        if args.direction in ("down", "right"):
            start, end = end, start
        self.log("swipe_target", node=node_info(node), start=start, end=end, coordinate_source="fresh_uiautomator_scrollable_bounds")
        self.run("shell", "input", "swipe", *(str(value) for value in [*start, *end, args.duration]))
        print(json.dumps({"swipe": args.direction, "start": start, "end": end, "duration_ms": args.duration}, ensure_ascii=False))


def add_selectors(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--text", help="Exact node text")
    parser.add_argument("--desc", help="Exact node content-desc")
    parser.add_argument("--resource-id", help="Exact node resource-id")
    parser.add_argument("--class", dest="class_name", help="Exact Android widget class")
    parser.add_argument("--index", type=int, help="Zero-based index among exact matches; required when ambiguous")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        sys.stderr.reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adb", required=True, help="Path to adb executable")
    parser.add_argument("--serial", required=True, help="Explicit adb target serial")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "adb-evidence")
    parser.add_argument("--timeout", type=float, default=45, help="Per-ADB-command timeout in seconds")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capture").add_argument("step")
    commands.add_parser("dump").add_argument("step", nargs="?", default="dump")
    summary = commands.add_parser("summary")
    summary.add_argument("--xml", type=Path)
    summary.add_argument("--fresh", action="store_true")
    add_selectors(commands.add_parser("tap"))
    commands.add_parser("input").add_argument("text")
    swipe = commands.add_parser("swipe")
    add_selectors(swipe)
    swipe.add_argument("--direction", choices=("up", "down", "left", "right"), default="up")
    swipe.add_argument("--duration", type=int, default=400)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.command == "swipe" and not 1 <= args.duration <= 10000:
        parser.error("--duration must be 1..10000 milliseconds")
    helper = ADBQA(args.adb, args.serial, args.out.resolve(), args.timeout)
    try:
        if args.command == "capture": helper.capture(args.step)
        elif args.command == "dump":
            root = helper.dump(args.step)
            print(json.dumps({"xml": str(helper.output / f"{args.step}.xml"), "nodes": len(list(root.iter("node")))}, ensure_ascii=False))
        elif args.command == "summary": helper.summary(args.xml, args.fresh)
        elif args.command == "tap": helper.tap(args)
        elif args.command == "input": helper.input_text(args.text)
        elif args.command == "swipe": helper.swipe(args)
    except (QAError, OSError, UnicodeError, ET.ParseError) as error:
        helper.log("failure", command=args.command, error=str(error))
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
