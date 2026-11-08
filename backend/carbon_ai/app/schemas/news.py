from datetime import datetime
from pydantic import BaseModel, Field


class IndustryNewsItem(BaseModel):
    id: int
    title: str
    summary: str
    source_name: str
    source_url: str
    tags: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    fetched_at: datetime


class IndustryNewsListResponse(BaseModel):
    data: list[IndustryNewsItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class IndustryNewsRefreshResponse(BaseModel):
    fetched: int
    inserted: int
    updated: int
    skipped: int
    embedded: int = 0
    filtered: int = 0
    cooldown_until: datetime | None = None
    message: str = Field(default="")


class IndustryNewsRefreshStartResponse(BaseModel):
    task_id: str
    status: str
    message: str = Field(default="")


class IndustryNewsRefreshStatusResponse(BaseModel):
    task_id: str
    status: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    embedded: int = 0
    filtered: int = 0
    pruned: int = 0
    fallback_layer: int = 0
    source: str = ""
    message: str = Field(default="")
    source_details: list[str] = Field(default_factory=list)


class IndustryNewsSemanticSearchResponse(BaseModel):
    data: list[IndustryNewsItem]
    total: int
    page: int
    page_size: int
    total_pages: int
    question: str
    track_tag: str | None = None


class IndustryNewsManualAddResponse(BaseModel):
    success: bool
    message: str = Field(default="")
    item: IndustryNewsItem | None = None


class IndustryNewsKGBackfillResponse(BaseModel):
    success: bool
    scanned: int = 0
    written: int = 0
    failed: int = 0
    skipped: int = 0
    message: str = Field(default="")


class NewsRefreshWithFallbackResponse(BaseModel):
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    filtered: int = 0
    pruned: int = 0
    embedded: int = 0
    fallback_layer: int = 0  # 0=live scrape, 1=keyword API, 2=DB cache
    source: str = ""
    message: str = ""
    source_details: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    db_cached_count: int = 0


class NewsDebugResponse(BaseModel):
    db_total_rows: int = 0
    db_latest_fetched_at: str | None = None
    db_sources: list[dict] = Field(default_factory=list)
    whitelist_sources: list[dict] = Field(default_factory=list)
    cooldown_active: bool = False
    cooldown_until: str | None = None
    crawler_state: dict = Field(default_factory=dict)
    time_window: str = "1w"
    active_crawl_windows: list[str] = Field(default_factory=list)
    keyword_sources_count: int = 0
    policy_keywords: list[str] = Field(default_factory=list)
