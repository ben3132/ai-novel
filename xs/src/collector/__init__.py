"""按可信等级硬编码约束的原始信源采集器。"""

from .derived_web_collector import DerivedWebCollector
from .reference_web_collector import L2WebCollector, L3WebCollector, L4WebCollector
from .reference_wiki_api_collector import ReferenceTranscriptApiCollector, ReferenceWikiApiL2Collector
from .official_index_follow_l1_collector import OfficialIndexFollowL1Collector
from .official_media_playlist_l1_collector import OfficialMediaPlaylistL1Collector
from .dynamic_web_l1_collector import DynamicWebL1Collector
from .local_l1_collector import LocalL1Collector
from .local_derived_text_collector import LocalDerivedTextCollector
from .lol_data_dragon_collector import LolDataDragonCollector
from .media_subtitle_collector import DerivedMediaSubtitleCollector, OfficialMediaSubtitleL1Collector
from .ocr_l1_collector import OcrL1Collector
from .official_api_l1_collector import OfficialApiL1Collector
from .official_document_l1_collector import OfficialDocumentL1Collector
from .derived_document_collector import DerivedDocumentCollector
from .official_web_l1_collector import OfficialWebL1Collector
from .official_site_crawl_l1_collector import OfficialSiteCrawlL1Collector

__all__ = [
    "DerivedWebCollector",
    "DynamicWebL1Collector",
    "LocalL1Collector",
    "LocalDerivedTextCollector",
    "LolDataDragonCollector",
    "DerivedMediaSubtitleCollector",
    "OfficialMediaSubtitleL1Collector",
    "OcrL1Collector",
    "OfficialApiL1Collector",
    "OfficialDocumentL1Collector",
    "DerivedDocumentCollector",
    "OfficialWebL1Collector",
    "OfficialSiteCrawlL1Collector",
    "L2WebCollector",
    "L3WebCollector",
    "L4WebCollector",
    "ReferenceWikiApiL2Collector",
]
