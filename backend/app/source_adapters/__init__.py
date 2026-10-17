"""Explicit, bounded registry. Adapters cannot perform network requests."""
from bs4 import BeautifulSoup

from .archive import ArchiveAdapter
from .base import SourceAdapter, SourceFacts
from .bilibili import BilibiliAdapter
from .icourse163 import ICourse163Adapter
from .mit_ocw import MITOCWAdapter
from .microsoft_curriculum import MicrosoftCurriculumAdapter


ADAPTERS: tuple[SourceAdapter, ...] = (
    MITOCWAdapter(), ArchiveAdapter(), MicrosoftCurriculumAdapter(), BilibiliAdapter(), ICourse163Adapter(),
)


def extract_source_facts(soup: BeautifulSoup, url: str) -> SourceFacts:
    for adapter in ADAPTERS:
        if adapter.matches(url):
            return adapter.extract(soup, url)
    return SourceFacts()
