from pathlib import Path
import hashlib,json
import pytest
from backend.app.extractor import MetadataExtractor
from backend.app.source_adapters.kaoyan import extract_embedded_kaoyan_facts,term_route
from backend.app.mooc_urls import public_course_url,course_identity_parts
from backend.app.fetcher import public_mooc_metadata_url

FIXTURE=Path(__file__).parent/'fixtures/kaoyan-term'
URL='https://kaoyan.icourse163.org/course/terms/1461621447.htm'
def html():
    return (FIXTURE/'observed-term.html').read_text('utf-8')
def extract(text=None,url=URL):
    return MetadataExtractor().extract(text if text is not None else html(),url,'offline-observed-html')

def test_observed_static_course_is_bound_to_term_not_fabricated_main_course():
    body=(FIXTURE/'observed-term.html').read_bytes()
    assert hashlib.sha256(body).hexdigest()==json.loads((FIXTURE/'manifest.json').read_text('utf-8'))['excerpt_sha256']
    r=extract()
    assert r['title']=='30天快速上手Python人工智能+数据分析'
    assert r['resource_type']=='course' and r['requires_payment'] is True
    assert '收费' in r['access_notice']
    assert r['chapters']==[] and r['video_evidence_status']=='none'
    assert not r.get('playback_verified') and not r.get('description')
    assert r['field_provenance']['resource_type']['source']=='html.kaoyan.course_info.bound_course_structure'
    row=next(row for row in r['evidence'] if row.get('field')=='resource_type')
    assert '1461621447' in row['text'] and '1460879165' in row['text'] and row['url']==URL
    assert public_course_url(URL) is None and course_identity_parts(URL) is None
    assert not public_mooc_metadata_url(URL)  # Static recognition never changes persistent fetch scope.

@pytest.mark.parametrize('before,after',[
 ('termId:1461621447','termId:1461621448'),('termId:1461621447','termId:true'),
 ('courseId:1460879165','courseId:true'),('courseId:1460879165','courseId:0'),
 ('courseId:1460879165','courseId:1.5'),('courseName:\'30天快速上手Python人工智能+数据分析\'','courseName:\'Wrong title\''),
 ('termId:1461621447','termId:1461621447,termId:1461621448'),
 ('termPrice:499','termPrice:(function(){return 499})()'),
 ('coursePackageName:\'Python课程（标签互导）\'','coursePackageName:\'unterminated\nvalue\''),
])
def test_wrong_identity_or_nonliteral_data_cannot_establish_course(before,after):
    raw=html();assert before in raw
    assert 'resource_type' not in extract(raw.replace(before,after))

@pytest.mark.parametrize('url',[
 'https://kaoyan.icourse163.org.evil.test/course/terms/1461621447.htm',
 'https://kaoyan.icourse163.org@evil.test/course/terms/1461621447.htm',
 'http://kaoyan.icourse163.org/course/terms/1461621447.htm',
 'https://kaoyan.icourse163.org:444/course/terms/1461621447.htm',
 URL+'?redirect=https://outside.test',URL+'#learn',
 'https://kaoyan.icourse163.org/course/terms/%31.htm',
 'https://kaoyan.icourse163.org/course/terms/１４６１６２１４４７.htm',
 'https://www.icourse163.org/course/terms/1461621447.htm',
])
def test_static_route_stays_exact_and_has_no_alias_or_host_wildcard(url):
    assert term_route(url) is None
    assert 'resource_type' not in extract(url=url)

def test_duplicate_payload_and_executable_assignment_are_not_static_evidence():
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(html(),'html.parser')
    script=soup.select_one('script')
    duplicate=html().replace('</body>',str(script)+'</body>')
    assert 'resource_type' not in extract(duplicate)
    assert 'resource_type' not in extract(html().replace('window.kaoyanCourseInfoVo =','window.kaoyanCourseInfoVo = build('))

@pytest.mark.parametrize('replacement',['0','true','-1'])
def test_unknown_or_zero_price_never_claims_free_access(replacement):
    r=extract(html().replace('termPrice:499','termPrice:'+replacement))
    assert r['resource_type']=='course'
    assert r.get('requires_payment') is not False
    assert not r.get('playback_verified') and r['chapters']==[]
