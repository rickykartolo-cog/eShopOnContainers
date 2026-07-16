"""Port of ``MarketingContextSeed``: two preconfigured campaigns with one
``UserLocationRule`` each, HiLo-generated ids, idempotent (seeds only when the
Campaign table is empty)."""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_fixed

from marketing_api.models import Campaign, UserLocationRule, campaign_hilo, rule_hilo

logger = structlog.get_logger(__name__)


@retry(reraise=True, stop=stop_after_attempt(4), wait=wait_fixed(5))
async def seed(session: AsyncSession) -> None:
    count = (await session.execute(select(func.count()).select_from(Campaign))).scalar_one()
    if count:
        return

    now = datetime.now()
    campaigns = [
        (
            ".NET Bot Black Hoodie 50% OFF",
            "Campaign Description 1",
            now,
            now + timedelta(days=7),
            "http://externalcatalogbaseurltobereplaced/api/v1/campaigns/1/pic",
            "1.png",
            "Campaign is only for United States users.",
            1,
        ),
        (
            "Roslyn Red T-Shirt 3x2",
            "Campaign Description 2",
            now - timedelta(days=7),
            now + timedelta(days=14),
            "http://externalcatalogbaseurltobereplaced/api/v1/campaigns/2/pic",
            "2.png",
            "Campaign is only for Seattle users.",
            3,
        ),
    ]
    for name, description, from_date, to_date, picture_uri, picture_name, rule_description, location_id in campaigns:
        campaign = Campaign(
            Id=await campaign_hilo.next_id(session),
            Name=name,
            Description=description,
            From=from_date,
            To=to_date,
            PictureUri=picture_uri,
            PictureName=picture_name,
        )
        session.add(campaign)
        session.add(
            UserLocationRule(
                Id=await rule_hilo.next_id(session),
                CampaignId=campaign.Id,
                Description=rule_description,
                LocationId=location_id,
            )
        )
    await session.commit()
    logger.info("marketing_seed_complete")
