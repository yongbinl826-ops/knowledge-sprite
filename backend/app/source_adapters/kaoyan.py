"""Static facts from an observed kaoyan course-introduction HTML template.

Recognition does not expand Fetcher permissions, manufacture a main-site
course URL, or discover chapter/player/private API endpoints.
"""
from __future__ import annotations
import json
import math
import re
from urllib.parse import urlsplit
from .base import SourceFacts, FieldFact, clean_text
from .icourse163 import _inline_objects
from ..url_utils import normalize_url, safe_thumbnail_url, UnsafeURL

SOURCE = 'html.kaoyan.course_info'

def term_route(url):
    if not isinstance(url, str) or url != url.strip():
        return None
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.hostname != 'kaoyan.icourse163.org'
                or parts.port not in {None,443} or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment):
            return None
        matched = re.fullmatch(r'/course/terms/([0-9]{1,20})\.htm', parts.path)
        return (normalize_url(url), matched[1]) if matched else None
    except (UnsafeURL,ValueError,TypeError):
        return None

def extract_embedded_kaoyan_facts(soup, url):
    facts = SourceFacts()
    route = term_route(url)
    if not route:
        return facts
    title_node = soup.select_one('.course-head-container .c-right .title')
    if title_node is None or soup.select_one('#j-course-info-tab-course') is None or soup.select_one('#j-course-chapter-box') is None:
        return facts
    title = clean_text(title_node.get_text(' ',strip=True),501)
    if not title or len(title) > 500:
        return facts
    payloads = []
    for script in soup.select('script:not([src])'):
        text = script.string or script.get_text()
        if not re.search(r'window\s*\.\s*kaoyanCourseInfoVo\s*=',text):
            continue
        if not re.fullmatch(r'\s*window\s*\.\s*kaoyanCourseInfoVo\s*=\s*\{[\s\S]*\}\s*;?\s*',text):
            return facts
        parsed = _inline_objects(text,names=frozenset({'kaoyanCourseInfoVo'}),single_quotes=True,allow_eof=True)
        if parsed is None:
            return facts
        payloads.append(parsed['kaoyanCourseInfoVo'])
    if len(payloads) != 1:
        return facts
    data = payloads[0]
    term, course = data.get('termId'), data.get('courseId')
    if (isinstance(term,bool) or isinstance(course,bool) or not isinstance(term,int) or not isinstance(course,int)
            or term <= 0 or course <= 0 or len(str(term)) > 20 or len(str(course)) > 20
            or str(term) != route[1] or clean_text(data.get('courseName'),501) != title):
        return facts
    binding = json.dumps({'term_id':str(term),'course_id':str(course),'route_namespace':'kaoyan-term'},ensure_ascii=False,sort_keys=True)
    facts.fields.extend([FieldFact('title',title,SOURCE+'.courseName',binding),
        FieldFact('resource_type','course',SOURCE+'.bound_course_structure',binding)])
    cover = soup.select_one('#j-course-img img[src]')
    image = safe_thumbnail_url(cover.get('src'),route[0]) if cover else None
    if image and image == safe_thumbnail_url(data.get('termBigPhoto'),route[0]):
        facts.fields.append(FieldFact('thumbnail_url',image,SOURCE+'.termBigPhoto',binding))
    price = data.get('termPrice')
    if (isinstance(price,(int,float)) and not isinstance(price,bool) and math.isfinite(price) and 0 < price <= 1_000_000_000):
        facts.fields.extend([FieldFact('requires_payment',True,SOURCE+'.termPrice',str(price)),
            FieldFact('access_notice','页面标示课程收费，试看及完整内容的可用性尚未核验。',SOURCE+'.access_notice',binding)])
    # The observed introduction is image-based and the curriculum container is
    # empty. Preview IDs and hidden buttons are not catalog or playback proof.
    return facts
