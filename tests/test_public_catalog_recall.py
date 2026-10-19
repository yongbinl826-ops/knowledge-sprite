from backend.app.queries import public_catalog_query


def test_translated_directory_query_preserves_original_unit_and_adds_no_source_identity():
    original = "pygame 网格地图、碰撞与重置"
    query = public_catalog_query(original)
    assert query.startswith(original)
    assert "grid" in query and "collision" in query and "reset" in query
    assert "http" not in query and "youtube" not in query


def test_other_projects_get_only_their_own_recall_vocabulary():
    query = public_catalog_query("pandas 时间解析与去重")
    assert "datetime parsing" in query and "drop_duplicates" in query
    assert "pygame" not in query and "collision" not in query and "Python basics" not in query
