from itertools import zip_longest
from .models import Query, SearchRequest

PLATFORMS = {"bilibili": "bilibili.com", "icourse163": "icourse163.org", "xuetangx": "xuetangx.com"}


def generate_queries(point_id: str, text: str, request: SearchRequest, expansions: list[str] | None = None) -> list[Query]:
    """Two open-web queries and one per preferred platform, at most six per point."""
    version = f" {request.technical_version.strip()}" if request.technical_version.strip() else ""
    level = {"beginner": "入门", "intermediate": "进阶", "advanced": "高级", "any": ""}[request.student_level]
    if request.language == "en":
        level = {"beginner": "beginner", "intermediate": "intermediate", "advanced": "advanced", "any": ""}[request.student_level]
        teaching, alternate = "video tutorial", "course lesson"
    else:
        teaching, alternate = "视频教程", "课程 教学"
    stem = f"{text}{version}"
    result = [Query(knowledge_point_id=point_id, query=f"{stem} {level} {teaching}".strip()),
              Query(knowledge_point_id=point_id, query=f"{stem} {alternate}")]
    for platform in dict.fromkeys(request.preferred_platforms):
        domain = PLATFORMS[platform]
        path = "/video" if platform == "bilibili" else ""
        result.append(Query(knowledge_point_id=point_id, query=f"site:{domain}{path} {stem} {teaching}", domain_filters=[domain]))
    if expansions:
        # Extension supplements the exact point, never replaces it or supplies URLs.
        result.append(Query(knowledge_point_id=point_id, query=f"{stem} {expansions[0]} {alternate}"))
    return result[:6]


def fair_queries(groups: list[list[Query]]) -> list[Query]:
    return [q for row in zip_longest(*groups) for q in row if q is not None]
