"""Project wording must not prevent bounded inspection of actual tool videos."""
from copy import deepcopy

from backend.app.service import JobService
from tests.test_video_readiness import record


def test_unparsed_project_unit_can_inspect_its_own_observed_tool_video():
    point = {"knowledge_point_id": "unit", "text": "pandas 读取骑行 CSV 与列结构检查"}
    resource, evidence = record("pandas CSV 视频教程")
    evidence[0].update(knowledge_point_id="unit", query="actual executed query")
    assert JobService._targeted_catalog_probe(point, resource, evidence, {})
    assert not JobService._targeted_catalog_probe(point, resource, evidence,
        {"gap_probes_started": {"unit": {"already-one", "already-two"}}})
    wrong = deepcopy(evidence)
    wrong[0]["knowledge_point_id"] = "another-unit"
    assert not JobService._targeted_catalog_probe(point, resource, wrong, {})
    wrong[0].update(knowledge_point_id="unit", title="PandasWrapper video tutorial")
    assert not JobService._targeted_catalog_probe(point, resource, wrong, {})
    wrong[0].update(title="pandas course", query="")
    assert not JobService._targeted_catalog_probe(point, resource, wrong, {})


def test_index_claim_and_untyped_page_never_supply_video_probe_or_teaching_evidence():
    point = {"knowledge_point_id": "unit", "text": "pygame 网格地图与墙壁阻挡"}
    resource, evidence = record("pygame video tutorial")
    evidence[0].update(knowledge_point_id="unit", query="query", source="techwithtim_catalog")
    assert not JobService._targeted_catalog_probe(point, resource, evidence, {})
    assert JobService._teaching_evidence(evidence) == []
