"""Two direct requests matching the fixed official Bing engine URL builder."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

OUT = Path(__file__).resolve().parent / "mooc-route-probe-20261013T090956Z"
source = r'''
import hashlib, json, time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from lxml import html
from searx.engines import bing
from searx.utils import gen_useragent
cases=[]
for query,locale in (("site:icourse163.org Python 列表与字典 课程", "zh-cn"), ("site:xuetangx.com linear algebra eigenvalues course", "en-us")):
    bing.traits=SimpleNamespace(get_region=lambda *args: locale, all_locale="clear")
    params={"searxng_locale": locale, "safesearch": 1}
    bing.request(query, params)
    case={"query":query,"engine_constructed_url":params["url"],"wire_decoded_q":parse_qs(urlsplit(params["url"]).query).get("q"),"transport":"direct urllib in same container; official engine URL builder and generated UA; not production engine transport"}
    try:
        response=build_opener(ProxyHandler({})).open(Request(params["url"],headers={"User-Agent":gen_useragent()}),timeout=10)
        content=response.read(2_000_000)
        case.update(http_status=response.status,response_url=response.url,body=content.decode("utf-8",errors="replace"),content_type=response.headers.get("content-type"),body_sha256=hashlib.sha256(content).hexdigest())
        document=html.fromstring(content.decode("utf-8",errors="replace"))
        case["input_query"]=document.xpath('//input[@name="q"]/@value')
        case["html_title"]=document.xpath('//title/text()')
        case["results"]=bing.response(SimpleNamespace(html=lambda: document))
    except HTTPError as error:
        case["http_status"]=error.code
        case["error_type"]=type(error).__name__
    except Exception as error:
        case["error_type"]=type(error).__name__
    cases.append(case)
    if case.get("http_status") in {401,403,429} or "captcha" in " ".join(case.get("html_title",[])).lower():
        break
    time.sleep(1)
print(json.dumps(cases,ensure_ascii=False))
'''
result = subprocess.run(["docker", "exec", "-i", "-w", "/usr/local/searxng", "knowledge-sprite-searxng-1", "/usr/local/searxng/.venv/bin/python", "-"], input=source.encode("utf-8"), capture_output=True)
if result.returncode:
    (OUT/"bing-direct-launch-error.txt").write_bytes(result.stderr)
    raise RuntimeError(result.stderr.decode("utf-8",errors="replace"))
cases=json.loads(result.stdout)
for index,case in enumerate(cases,1):
    if "body" in case:
        path=OUT/f"bing-direct-{index}.html"
        path.write_text(case.pop("body"),encoding="utf-8")
        case["body_file"]=path.name
report={"observed_at":datetime.now(timezone.utc).isoformat(),"requests":cases}
(OUT/"bing-direct-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
for case in cases:
    print(json.dumps({key:case.get(key) for key in ("query","http_status","wire_decoded_q","input_query","html_title","error_type")},ensure_ascii=True))
