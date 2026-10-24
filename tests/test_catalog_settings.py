"""Background catalog allowances are bounded independently of video latency."""
import pytest

from backend.app.config import Settings


@pytest.mark.parametrize("field,minimum,maximum", [
    ("catalog_background_seconds", 1, 900),
    ("catalog_background_max_resources", 12, 96),
    ("catalog_background_max_http_requests", 18, 384),
    ("catalog_background_max_model_calls", 3, 32),
])
def test_catalog_allowances_reject_unbounded_or_wrong_type_values(field, minimum, maximum):
    for value in (minimum - 1, maximum + 1, True, 3.5):
        with pytest.raises(ValueError, match=field.upper()):
            Settings(**{field: value}).validate()
    for value in (minimum, maximum):
        assert getattr(Settings(**{field: value}).validate(), field) == value


def test_catalog_environment_keeps_video_deadline_separate(monkeypatch):
    values = {"CATALOG_BACKGROUND_SECONDS": "450", "CATALOG_BACKGROUND_MAX_RESOURCES": "64",
              "CATALOG_BACKGROUND_MAX_HTTP_REQUESTS": "192", "CATALOG_BACKGROUND_MAX_MODEL_CALLS": "16"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("FAST_VIDEO_DEADLINE_SECONDS", "110")
    configured = Settings.from_env()
    assert configured.fast_video_deadline_seconds == 110
    assert [getattr(configured, name.lower()) for name in values] == [450, 64, 192, 16]


@pytest.mark.parametrize("name", ["CATALOG_BACKGROUND_SECONDS", "CATALOG_BACKGROUND_MAX_RESOURCES",
                                  "CATALOG_BACKGROUND_MAX_HTTP_REQUESTS", "CATALOG_BACKGROUND_MAX_MODEL_CALLS"])
def test_invalid_catalog_environment_fails_instead_of_silently_expanding(name, monkeypatch):
    monkeypatch.setenv(name, "unlimited")
    with pytest.raises(ValueError, match=name):
        Settings.from_env()
