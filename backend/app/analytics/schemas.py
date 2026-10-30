from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class AnalyticsSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current_clicks: int
    previous_clicks: int
    percent_change: Optional[float] = None
    resolved_start_date: str
    resolved_end_date: str
    tz: str
    link_id: Optional[int] = None


class TimeseriesItem(BaseModel):
    date: str
    click_count: int


class AnalyticsTimeseriesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: List[TimeseriesItem]
    resolved_start_date: str
    resolved_end_date: str
    tz: str
    link_id: Optional[int] = None


class TopLinkItem(BaseModel):
    id: int
    short_code: str
    short_url: str
    original_url: str
    click_count: int


class AnalyticsTopLinksResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: List[TopLinkItem]
    resolved_start_date: str
    resolved_end_date: str
    tz: str


class BreakdownItem(BaseModel):
    name: str
    click_count: int
    percentage: float


class AnalyticsBreakdownResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    referrers: List[BreakdownItem]
    devices: List[BreakdownItem]
    total_clicks: int
    resolved_start_date: str
    resolved_end_date: str
    tz: str
    link_id: Optional[int] = None
