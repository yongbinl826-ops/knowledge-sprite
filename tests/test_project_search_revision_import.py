"""Offline synthetic fixtures for the acceptance-only retained-analysis importer."""
from copy import deepcopy
import hashlib
import json

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.project_db import ProjectStore
from backend.app.project_models import ProjectInput
from backend.app.project_service import ProjectError, ProjectService
from scripts.validate_project_search_revision import import_retained_analysis, table_counts


def fixture(tmp_path):
    input_data = ProjectInput(name="离线导入测试", requirements="读取本地表格并统计结果").model_dump()
    analysis = {"scope": "离线样本", "technical_plan": "本地 Python 脚本", "assumptions": [],
        "functions": [{"id": "f1", "name": "统计", "original_requirement": "统计表格",
            "acceptance_criteria": "输出统计结果", "no_new_learning_reason": None}],
        "knowledge_points": [{"id": "k1", "name": "pandas 读取 Excel", "description": "读取数据",
            "function_ids": ["f1"], "why_needed": "读取表格", "learning_goal": "能读取本地 Excel",
            "necessity": "required", "prerequisite_ids": [], "learning_order": 1, "selection": "learn"}]}
    source = {"project_id": "source-offline-project", "input": input_data, "current_version": 1,
        "version": {"version": 1, "input": input_data, "analysis": analysis, "model": "offline-fixture",
            "prompt_version": "offline-prompt", "confirmation": {"confirmation_version": 1,
                "confirmed_at": "2026-10-17T00:00:00Z", "input": deepcopy(input_data),
                "analysis": deepcopy(analysis), "selected_ids": ["k1"], "selections": {"k1": "learn"}}}}
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    database = tmp_path / "fresh.sqlite3"
    store = Store(str(database))
    ProjectStore(store)
    store.close()
    return source_path, database, source


def test_import_is_unconfirmed_namespaced_and_contains_no_search_data(tmp_path):
    source, database, _ = fixture(tmp_path)
    metadata = import_retained_analysis(source, database, 1)
    assert metadata["project_id"] != "source-offline-project"
    assert metadata["provenance"]["source_file_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert metadata["provenance"]["new_model_analysis_performed"] is False
    store = Store(str(database))
    try:
        projects = ProjectService(Settings(database_path=str(database)), store, jobs=None)
        view = projects.view(metadata["project_id"])
        assert view["version"]["origin"] == "retained_analysis"
        assert view["version"]["status"] == "analyzed" and view["version"]["confirmation"] is None
        assert view["version"]["batches"] == [] and view["version"]["search_started_at"] is None
        assert view["version"]["analysis"]["knowledge_points"][0]["id"] == "k1"
        with pytest.raises(ProjectError) as error:
            projects.search(metadata["project_id"], 1)
        assert error.value.code == "confirmation_required"
        confirmed = projects.confirm(metadata["project_id"], 1, [])
        assert confirmed["version"]["confirmation"]["selected_ids"] == ["k1"]
        counts = table_counts(store.connection)
        assert counts["jobs"] == counts["resources"] == counts["cache"] == counts["project_batches"] == 0
    finally:
        store.close()


@pytest.mark.parametrize("change", ["confirmation", "selection", "cycle", "count"])
def test_invalid_source_is_rejected_before_any_target_write(tmp_path, change):
    source, database, data = fixture(tmp_path)
    if change == "confirmation":
        data["version"]["confirmation"]["confirmation_version"] = 2
    elif change == "selection":
        data["version"]["confirmation"]["selected_ids"] = []
    elif change == "cycle":
        data["version"]["analysis"]["knowledge_points"][0]["prerequisite_ids"] = ["k1"]
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        import_retained_analysis(source, database, 2 if change == "count" else 1)
    store = Store(str(database))
    assert not any(table_counts(store.connection).values())
    store.close()


def test_nonempty_cache_and_repeat_import_are_rejected(tmp_path):
    source, database, _ = fixture(tmp_path)
    store = Store(str(database))
    store.cache_set("existing", "search", [], 60)
    store.close()
    with pytest.raises(ValueError, match="must be empty"):
        import_retained_analysis(source, database, 1)
    store = Store(str(database))
    assert table_counts(store.connection)["cache"] == 1
    assert table_counts(store.connection)["projects"] == 0
    store.connection.execute("DELETE FROM cache")
    store.connection.commit()
    store.close()
    first = import_retained_analysis(source, database, 1)
    with pytest.raises(ValueError, match="must be empty"):
        import_retained_analysis(source, database, 1)
    assert first["after_table_counts"]["projects"] == 1


def test_failed_project_save_rolls_back_the_entire_import(tmp_path, monkeypatch):
    source, database, _ = fixture(tmp_path)
    original_save = ProjectStore.save
    def fail_after_save(self, *args, **kwargs):
        original_save(self, *args, **kwargs)
        raise RuntimeError("synthetic post-save failure")
    monkeypatch.setattr(ProjectStore, "save", fail_after_save)
    with pytest.raises(RuntimeError):
        import_retained_analysis(source, database, 1)
    store = Store(str(database))
    assert not any(table_counts(store.connection).values())
    store.close()
