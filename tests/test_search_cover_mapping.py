import json
import httpx
import pytest

from backend.app.config import Settings
from backend.app.providers import SerperProvider, TavilyProvider, parse_candidates

VIDEO = "https://www.bilibili.com/video/BV15L4y1a7or"
COVER = "https://i1.hdslb.com/bfs/archive/test-cover.jpg"


@pytest.mark.asyncio
async def test_serper_video_hit_contains_own_cover_in_one_request():
    calls=[]
    def response(request):
        calls.append(request)
        assert str(request.url) == "https://google.serper.dev/videos"
        return httpx.Response(200,json={"videos":[{"title":"Video", "link":VIDEO,
            "snippet":"JavaScript", "imageUrl":COVER}],"credits":1})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider=SerperProvider(Settings(serper_api_key="test"),client)
        rows=await provider.search("JavaScript","zh",5,["bilibili.com"])
    assert len(calls)==1 and rows[0].thumbnail_url==COVER and rows[0].url==VIDEO
    assert rows[0].resource_type_hint=="video"
    assert provider.last_requests[0]["search_mode"]=="videos"


@pytest.mark.asyncio
async def test_tavily_enables_images_but_does_not_pair_query_images_to_results():
    def response(request):
        assert json.loads(request.content)["include_images"] is True
        return httpx.Response(200,json={"images":[COVER], "results":[
            {"title":"No poster", "url":VIDEO,"images":[{"url":COVER,"description":"page visual"}]},
            {"title":"Bound poster", "url":VIDEO+"?p=2", "images":[{"url":COVER,"role":"poster"}]}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        rows=await TavilyProvider(Settings(tavily_api_key="test"),client).search("JavaScript","zh",5,["bilibili.com"])
    assert rows[0].thumbnail_url is None and rows[1].thumbnail_url==COVER


@pytest.mark.parametrize("image", [
    {"url":COVER,"role":"poster","source_url":"https://www.bilibili.com/video/BV1Other99999"},
    {"url":"http://127.0.0.1/private","role":"poster"},
    {"url":COVER,"role":"avatar"},
])
def test_unbound_or_unsafe_images_cannot_become_posters(image):
    rows=parse_candidates([{"title":"Video","url":VIDEO,"images":[image]}],"tavily","js",5,[])
    assert rows[0].thumbnail_url is None


@pytest.mark.parametrize("role", [{}, [], None, 42])
def test_malformed_image_role_does_not_drop_the_result_or_next_valid_cover(role):
    rows = parse_candidates([{"title": "Video", "url": VIDEO, "images": [
        {"url": COVER, "role": role}, {"url": COVER, "role": "poster"}]}], "tavily", "js", 5, [])
    assert len(rows) == 1 and rows[0].thumbnail_url == COVER
