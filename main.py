"""
ForaGo Backend - FastAPI + PostgreSQL
Main application file with routes
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, field_validator
import os
from dotenv import load_dotenv
import asyncio

from database import init_db, close_db, run_migrations
from auth import AuthUser, get_current_user, validate_auth_configuration
from queries import (
    query_public_finds,
    query_private_finds,
    query_finds_nearby,
    insert_find,
    get_find_by_id,
    update_find as db_update_find,
    delete_find as db_delete_find,
    query_clusters,
)

load_dotenv()

DATA_SOURCE_MODE = os.getenv("DATA_SOURCE_MODE", "mock").lower()
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()


def _is_production_env() -> bool:
    return ENVIRONMENT in {"production", "prod"}


def _validate_startup_configuration() -> None:
    if _is_production_env() and DATA_SOURCE_MODE != "db":
        raise RuntimeError("Production requires DATA_SOURCE_MODE=db")

    validate_auth_configuration(is_production=_is_production_env())

# ============ CONFIG ============
app = FastAPI(
    title="ForaGo API",
    version="1.0.0",
    description="Backend for ForaGo bushcraft app"
)

# CORS settings - allow Flutter (localhost:port) and web (Cloudflare Pages)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://127.0.0.1",
        "https://forago.app",
    ],
    allow_origin_regex=r"^https://([a-zA-Z0-9-]+\.)*forago\.pages\.dev$|^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ SCHEMAS (Pydantic) ============
class LatLng(BaseModel):
    latitude: float
    longitude: float

class RecordImageRef(BaseModel):
    thumbnailUrl: str
    fullUrl: str
    storageRef: Optional[str] = None

class RecordComment(BaseModel):
    id: str
    userId: str
    text: str
    createdAt: datetime

class PublicFindRecord(BaseModel):
    id: str
    userId: str
    date: datetime
    categoryPaths: List[List[str]]
    description: str
    clusterHash: str
    period: Optional[str] = None
    images: List[RecordImageRef] = []
    comments: List[RecordComment] = []

class PrivateFindRecord(PublicFindRecord):
    location: LatLng

class PublicClusterRecord(BaseModel):
    clusterHash: str
    categoryPathCounts: dict
    totalRecords: int
    lastUpdated: datetime


class AuthMeResponse(BaseModel):
    userId: str
    issuer: Optional[str] = None
    audience: Optional[str] = None

VALID_PERIODS = {
    "JAN_1", "JAN_2", "FEB_1", "FEB_2", "MAR_1", "MAR_2",
    "APR_1", "APR_2", "MAY_1", "MAY_2", "JUN_1", "JUN_2",
    "JUL_1", "JUL_2", "AUG_1", "AUG_2", "SEP_1", "SEP_2",
    "OCT_1", "OCT_2", "NOV_1", "NOV_2", "DEC_1", "DEC_2",
}


class CreateFindRequest(BaseModel):
    date: datetime
    categoryPaths: List[List[str]]
    description: str
    location: LatLng
    clusterHash: str
    period: Optional[str] = None

    @field_validator('period')
    @classmethod
    def validate_period(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PERIODS:
            raise ValueError(f'Invalid period "{v}". Valid values: {sorted(VALID_PERIODS)}')
        return v


class UpdateFindRequest(BaseModel):
    date: Optional[datetime] = None
    categoryPaths: Optional[List[List[str]]] = None
    description: Optional[str] = None
    location: Optional[LatLng] = None
    period: Optional[str] = None

    @field_validator('period')
    @classmethod
    def validate_period(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PERIODS:
            raise ValueError(f'Invalid period "{v}". Valid values: {sorted(VALID_PERIODS)}')
        return v

# ============ MOCK DATA (temporary) ============
MOCK_FINDS = {
    "rec_001": PrivateFindRecord(
        id="rec_001",
        userId="user_jan",
        date=datetime.now(),
        categoryPaths=[["nature", "forest", "tree"]],
        description="Tall oak tree near village",
        clusterHash="48.71_19.15",
        location=LatLng(latitude=48.7145, longitude=19.1523),
    ),
    "rec_002": PublicFindRecord(
        id="rec_002",
        userId="user_maria",
        date=datetime.now(),
        categoryPaths=[["edible", "mushroom", "porcini"]],
        description="Porcini mushrooms found",
        clusterHash="48.71_19.15",
    ),
}


def _public_records_from_mock() -> List[PublicFindRecord]:
    return [
        find
        for find in MOCK_FINDS.values()
        if isinstance(find, PublicFindRecord)
        and not isinstance(find, PrivateFindRecord)
    ]


def _private_records_from_mock() -> List[PrivateFindRecord]:
    return [
        find for find in MOCK_FINDS.values() if isinstance(find, PrivateFindRecord)
    ]


def _matches_category_filter(record: PublicFindRecord, category: Optional[str]) -> bool:
    if not category:
        return True

    segments = [segment for segment in category.split("/") if segment]
    if not segments:
        return True

    for path in record.categoryPaths:
        if len(path) < len(segments):
            continue
        if path[: len(segments)] == segments:
            return True
    return False


def _matches_date_filter(
    record: PublicFindRecord,
    from_date: Optional[datetime],
    to_date: Optional[datetime],
) -> bool:
    if from_date and record.date < from_date:
        return False
    if to_date and record.date > to_date:
        return False
    return True


def _matches_period_filter(record: PublicFindRecord, period: Optional[str]) -> bool:
    if not period:
        return True
    return record.period == period


# ============ ROUTES ============

@app.get("/api/auth/me", response_model=AuthMeResponse)
async def auth_me(current_user: AuthUser = Depends(get_current_user)):
    """Return identity resolved from Bearer token."""
    claims = current_user.claims
    audience = claims.get("aud")
    if isinstance(audience, list):
        audience = ",".join(audience)
    if audience is not None and not isinstance(audience, str):
        audience = str(audience)

    issuer = claims.get("iss")
    if issuer is not None and not isinstance(issuer, str):
        issuer = str(issuer)

    return AuthMeResponse(
        userId=current_user.user_id,
        issuer=issuer,
        audience=audience,
    )

@app.get("/api/health")
async def health_check():
    """Health check - used by monitoring"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow(),
        "version": "1.0.0",
        "dataSourceMode": DATA_SOURCE_MODE,
    }

# ---------- FINDS ENDPOINTS ----------

@app.get("/api/finds/public", response_model=List[PublicFindRecord])
async def get_public_finds(
    cluster: Optional[str] = None,
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
):
    """
    Get all public finds (visible to all users)
    Filter by cluster, category, date range, period
    """
    try:
        if DATA_SOURCE_MODE == "db":
            results_data = await query_public_finds(
                cluster=cluster,
                category=category,
                from_date=from_date,
                to_date=to_date,
                period=period,
            )
            return [PublicFindRecord(**r) for r in results_data]
        else:
            # Mock mode
            results = _public_records_from_mock()

            if cluster:
                results = [f for f in results if f.clusterHash == cluster]

            if category:
                results = [f for f in results if _matches_category_filter(f, category)]

            if from_date or to_date:
                results = [f for f in results if _matches_date_filter(f, from_date, to_date)]

            if period:
                results = [f for f in results if _matches_period_filter(f, period)]

            return results
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database query failed: {str(e)}",
        )

@app.get("/api/finds/nearby", response_model=List[PublicFindRecord])
async def get_finds_nearby(
    cluster: str,
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
):
    """Get finds near a specific cluster"""
    try:
        if DATA_SOURCE_MODE == "db":
            results_data = await query_finds_nearby(
                cluster=cluster,
                category=category,
                from_date=from_date,
                to_date=to_date,
                period=period,
            )
            return [PublicFindRecord(**r) for r in results_data]
        else:
            # Mock mode
            results = [
                find
                for find in _public_records_from_mock()
                if find.clusterHash == cluster
            ]

            if category:
                results = [f for f in results if _matches_category_filter(f, category)]

            if from_date or to_date:
                results = [f for f in results if _matches_date_filter(f, from_date, to_date)]

            if period:
                results = [f for f in results if _matches_period_filter(f, period)]

            return results
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database query failed: {str(e)}",
        )

@app.get("/api/finds/private", response_model=List[PrivateFindRecord])
async def get_private_finds(
    cluster: Optional[str] = None,
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
    current_user: AuthUser = Depends(get_current_user),
):
    """
    Get current user's private finds
    Requires authentication
    """
    try:
        effective_user_id = current_user.user_id

        if DATA_SOURCE_MODE == "db":
            results_data = await query_private_finds(
                user_id=effective_user_id,
                cluster=cluster,
                category=category,
                from_date=from_date,
                to_date=to_date,
                period=period,
            )
            return [PrivateFindRecord(**r) for r in results_data]
        else:
            # AUTH-TEMP: Remove dev user fallback after JWT is wired.
            results = [
                find for find in _private_records_from_mock() if find.userId == effective_user_id
            ]

            if cluster:
                results = [f for f in results if f.clusterHash == cluster]

            if category:
                results = [f for f in results if _matches_category_filter(f, category)]

            if from_date or to_date:
                results = [f for f in results if _matches_date_filter(f, from_date, to_date)]

            if period:
                results = [f for f in results if _matches_period_filter(f, period)]

            return results
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database query failed: {str(e)}",
        )

@app.post("/api/finds", response_model=PrivateFindRecord, status_code=status.HTTP_201_CREATED)
async def create_find(
    request: CreateFindRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """
    Create new find record
    Returns PrivateFindRecord with exact location
    """
    try:
        effective_user_id = current_user.user_id

        if DATA_SOURCE_MODE == "db":
            result_data = await insert_find(
                user_id=effective_user_id,
                date=request.date,
                description=request.description,
                cluster_hash=request.clusterHash,
                latitude=request.location.latitude,
                longitude=request.location.longitude,
                category_paths=request.categoryPaths,
                period=request.period,
            )
            return PrivateFindRecord(**result_data)
        else:
            # Mock mode
            new_find = PrivateFindRecord(
                id=f"rec_{len(MOCK_FINDS) + 1:03d}",
                userId=effective_user_id,
                date=request.date,
                categoryPaths=request.categoryPaths,
                description=request.description,
                clusterHash=request.clusterHash,
                location=request.location,
                period=request.period,
            )
            MOCK_FINDS[new_find.id] = new_find
            return new_find
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create find: {str(e)}",
        )

@app.get("/api/finds/{find_id}", response_model=PrivateFindRecord)
async def get_find(find_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Get find by ID (if user has access)"""
    try:
        if DATA_SOURCE_MODE == "db":
            result = await get_find_by_id(find_id, current_user.user_id)
            if result is None:
                raise HTTPException(status_code=404, detail="Find not found")
            return PrivateFindRecord(**result)
        else:
            if find_id not in MOCK_FINDS:
                raise HTTPException(status_code=404, detail="Find not found")
            record = MOCK_FINDS[find_id]
            if isinstance(record, PrivateFindRecord) and record.userId == current_user.user_id:
                return record
            raise HTTPException(status_code=403, detail="Access denied")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

@app.put("/api/finds/{find_id}", response_model=PrivateFindRecord)
async def update_find(
    find_id: str,
    request: UpdateFindRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Update find"""
    try:
        if DATA_SOURCE_MODE == "db":
            result = await db_update_find(
                find_id=find_id,
                user_id=current_user.user_id,
                date=request.date,
                description=request.description,
                latitude=request.location.latitude if request.location else None,
                longitude=request.location.longitude if request.location else None,
                category_paths=request.categoryPaths,
                period=request.period,
            )
            if result is None:
                raise HTTPException(status_code=404, detail="Find not found")
            return PrivateFindRecord(**result)
        else:
            if find_id not in MOCK_FINDS:
                raise HTTPException(status_code=404, detail="Find not found")
            existing = MOCK_FINDS[find_id]
            if not isinstance(existing, PrivateFindRecord) or existing.userId != current_user.user_id:
                raise HTTPException(status_code=403, detail="Access denied")
            updated = existing.model_copy(update={
                k: v for k, v in {
                    "date": request.date,
                    "categoryPaths": request.categoryPaths,
                    "description": request.description,
                    "location": request.location,
                    "period": request.period,
                }.items() if v is not None
            })
            MOCK_FINDS[find_id] = updated
            return updated
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update find: {str(e)}")

@app.delete("/api/finds/{find_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_find(find_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Delete find.

    Requires authentication and ownership.
    """
    try:
        if DATA_SOURCE_MODE == "db":
            deleted = await db_delete_find(find_id, current_user.user_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Find not found")
        else:
            if find_id not in MOCK_FINDS:
                raise HTTPException(status_code=404, detail="Find not found")
            if not isinstance(MOCK_FINDS[find_id], PrivateFindRecord) or MOCK_FINDS[find_id].userId != current_user.user_id:
                raise HTTPException(status_code=403, detail="Access denied")
            del MOCK_FINDS[find_id]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete find: {str(e)}")

# ---------- CLUSTERS ENDPOINTS ----------

@app.get("/api/clusters", response_model=List[PublicClusterRecord])
async def get_clusters(
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
):
    """
    Get aggregated cluster data
    Returns cluster stats without revealing exact locations
    """
    try:
        if DATA_SOURCE_MODE == "db":
            results_data = await query_clusters(
                category=category,
                from_date=from_date,
                to_date=to_date,
            )
            return [PublicClusterRecord(**r) for r in results_data]
        else:
            clusters = {
                "51.5_-0.1": PublicClusterRecord(
                    clusterHash="51.5_-0.1",
                    categoryPathCounts={
                        "nature/forest/tree": 1,
                        "edible/mushroom/porcini": 1,
                    },
                    totalRecords=2,
                    lastUpdated=datetime.now(),
                )
            }
            return list(clusters.values())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cluster query failed: {str(e)}")

# ============ ERROR HANDLERS ============

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom error response"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status": exc.status_code,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

# ============ STARTUP / SHUTDOWN ============

@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    _validate_startup_configuration()

    print("🚀 ForaGo API started")
    print(f"📖 Docs: http://localhost:8000/docs")
    print(f"🔧 ReDoc: http://localhost:8000/redoc")
    print(f"🗂️ Data source mode: {DATA_SOURCE_MODE}")
    
    if DATA_SOURCE_MODE == "db":
        try:
            await init_db()
            await run_migrations()
            print("✓ Database initialized and migrations applied")
        except Exception as e:
            print(f"✗ Database initialization failed: {e}")
            raise


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    if DATA_SOURCE_MODE == "db":
        try:
            await close_db()
        except Exception as e:
            print(f"✗ Database shutdown error: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
