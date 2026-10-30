from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.auth.dependencies import get_current_user
from app.users.models import User
from app.analytics.schemas import (
    AnalyticsSummaryResponse,
    AnalyticsTimeseriesResponse,
    AnalyticsTopLinksResponse,
    AnalyticsBreakdownResponse,
)
from app.analytics.service import (
    get_analytics_summary,
    get_analytics_timeseries,
    get_analytics_top_links,
    get_analytics_breakdown,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def analytics_summary_endpoint(
    range: int = Query(default=30, description="Range in days: 7, 30, or 90"),
    tz: str = Query(default="UTC", description="IANA timezone name"),
    link_id: Optional[int] = Query(default=None, ge=1, le=9223372036854775807, description="Optional link filter"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get aggregated click counts for current period vs previous period,
    and percent change.
    """
    return get_analytics_summary(
        db=db,
        user_id=current_user.id,
        range_days=range,
        tz_name=tz,
        link_id=link_id,
    )


@router.get("/timeseries", response_model=AnalyticsTimeseriesResponse)
def analytics_timeseries_endpoint(
    range: int = Query(default=30, description="Range in days: 7, 30, or 90"),
    tz: str = Query(default="UTC", description="IANA timezone name"),
    link_id: Optional[int] = Query(default=None, ge=1, le=9223372036854775807, description="Optional link filter"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get zero-filled daily timeseries for the last N calendar days in user's timezone.
    """
    return get_analytics_timeseries(
        db=db,
        user_id=current_user.id,
        range_days=range,
        tz_name=tz,
        link_id=link_id,
    )


@router.get("/top-links", response_model=AnalyticsTopLinksResponse)
def analytics_top_links_endpoint(
    range: int = Query(default=30, description="Range in days: 7, 30, or 90"),
    tz: str = Query(default="UTC", description="IANA timezone name"),
    limit: int = Query(default=10, ge=1, le=50, description="Number of links to return"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get user's top links by click count over the specified period.
    """
    return get_analytics_top_links(
        db=db,
        user_id=current_user.id,
        range_days=range,
        tz_name=tz,
        limit=limit,
    )


@router.get("/breakdown", response_model=AnalyticsBreakdownResponse)
def analytics_breakdown_endpoint(
    range: int = Query(default=30, description="Range in days: 7, 30, or 90"),
    tz: str = Query(default="UTC", description="IANA timezone name"),
    link_id: Optional[int] = Query(default=None, ge=1, le=9223372036854775807, description="Optional link filter"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get breakdown by referrers (top 10 + Direct + Other) and devices.
    """
    return get_analytics_breakdown(
        db=db,
        user_id=current_user.id,
        range_days=range,
        tz_name=tz,
        link_id=link_id,
    )
