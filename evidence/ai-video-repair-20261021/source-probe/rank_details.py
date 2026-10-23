"""Run unchanged production ranker on live fetched evidence, without network."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from backend.app.models import SearchRequest
from backend.app.ranking import rank_resource
from backend.app.related_recommendations import related_recommendation
OUT=Path(__file__).resolve().parent
report=[]
for filename in ("details-report.json","pygame-details-report.json","pandas-details-report.json"):
    for i,row in enumerate(json.loads((OUT/filename).read_text(encoding="utf-8"))["details"]):
        resource=dict(row["result"])
        resource["resource_id"]=f"diagnostic_{i}"
        point={"knowledge_point_id":f"kp_{i}","text":row["point"]}
        request=SearchRequest(knowledge_points=[row["point"]],preferred_platforms=["bilibili"])
        result=rank_resource(point,resource,resource["evidence"],request)
        related=related_recommendation(point,resource,resource["evidence"],request)
        report.append({"point":row["point"],"title":resource.get("title"),"url":resource["url"],"rank":result,"related_reference":related})
(OUT/"ranking-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps([{"point":r["point"],"url":r["url"],"strict":r["rank"] is not None,"related":r["related_reference"] is not None} for r in report],ensure_ascii=False,indent=2))
