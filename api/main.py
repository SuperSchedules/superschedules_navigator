"""FastAPI application for Superschedules Navigator."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.navigator import discover_site_navigation

app = FastAPI(
    title="Superschedules Navigator",
    description="Discover event pages and navigation patterns on websites",
    version="1.0.0",
)

# Thread pool for running sync code in async context
executor = ThreadPoolExecutor(max_workers=4)


class TargetSchema(BaseModel):
    """Schema definition for target content type."""
    type: str = "events"
    required_fields: List[str] = ["title", "date", "location"] 
    content_indicators: List[str] = ["calendar", "event", "workshop", "meeting"]


class DiscoverRequest(BaseModel):
    """Request model for site navigation discovery."""
    base_url: str
    target_schema: Optional[TargetSchema] = None
    max_depth: Optional[int] = 3
    follow_external_links: Optional[bool] = False


class NavigationStrategy(BaseModel):
    """Navigation and pagination strategy."""
    pagination_type: Optional[str] = None  # "next_button", "numbered", "infinite_scroll"
    pagination_selector: Optional[str] = None
    items_per_page: Optional[int] = None


class SiteProfile(BaseModel):
    """Discovered site navigation profile."""
    domain: str
    event_urls: List[str]
    url_patterns: List[str]
    navigation_strategy: NavigationStrategy
    discovered_filters: Dict[str, str]
    skip_patterns: List[str]


class DiscoverResponse(BaseModel):
    """Response model for navigation discovery."""
    success: bool
    site_profile: Optional[SiteProfile] = None
    confidence: float
    processing_time_seconds: float
    error_message: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    timestamp: str
    version: str


def _discover_sync(base_url: str, target_schema: Optional[TargetSchema], max_depth: int, 
                  follow_external_links: bool) -> Dict:
    """Synchronous navigation discovery function."""
    try:
        result = discover_site_navigation(
            base_url=base_url,
            target_schema=target_schema.dict() if target_schema else None,
            max_depth=max_depth,
            follow_external_links=follow_external_links
        )
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat(),
        version="1.0.0"
    )


@app.get("/live", response_model=HealthResponse) 
async def liveness_check():
    """Liveness check endpoint."""
    return HealthResponse(
        status="alive",
        timestamp=datetime.utcnow().isoformat(),
        version="1.0.0"
    )


@app.get("/ready", response_model=HealthResponse)
async def readiness_check():
    """Readiness check endpoint."""
    return HealthResponse(
        status="ready", 
        timestamp=datetime.utcnow().isoformat(),
        version="1.0.0"
    )


@app.post("/discover", response_model=DiscoverResponse)
async def discover_navigation(request: DiscoverRequest):
    """
    Discover event pages and navigation patterns for a website.
    
    This endpoint analyzes a website to find:
    - Specific URLs containing events
    - URL patterns for systematic crawling  
    - Pagination and navigation strategies
    - Available filters for targeted scraping
    """
    start_time = datetime.utcnow()
    
    try:
        # Run discovery in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor,
            _discover_sync,
            request.base_url,
            request.target_schema,
            request.max_depth or 3,
            request.follow_external_links or False
        )
        
        if "error" in result:
            end_time = datetime.utcnow()
            processing_time = (end_time - start_time).total_seconds()
            
            return DiscoverResponse(
                success=False,
                confidence=0.0,
                processing_time_seconds=processing_time,
                error_message=result["error"]
            )
        
        # Parse domain from URL
        parsed_url = urlparse(request.base_url)
        domain = parsed_url.netloc
        
        # Build site profile
        site_profile = SiteProfile(
            domain=domain,
            event_urls=result.get("event_urls", []),
            url_patterns=result.get("url_patterns", []),
            navigation_strategy=NavigationStrategy(
                pagination_type=result.get("pagination_type"),
                pagination_selector=result.get("pagination_selector"), 
                items_per_page=result.get("items_per_page")
            ),
            discovered_filters=result.get("discovered_filters", {}),
            skip_patterns=result.get("skip_patterns", [])
        )
        
        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds()
        
        return DiscoverResponse(
            success=True,
            site_profile=site_profile,
            confidence=result.get("confidence", 0.5),
            processing_time_seconds=processing_time
        )
        
    except Exception as e:
        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds()
        
        return DiscoverResponse(
            success=False,
            confidence=0.0,
            processing_time_seconds=processing_time,
            error_message=f"Discovery failed: {str(e)}"
        )


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Superschedules Navigator",
        "version": "1.0.0", 
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)