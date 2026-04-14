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
from r2_storage import generate_find_image_upload_plans, is_r2_configured
from version import __version__
from queries import (
    query_public_finds,
    query_private_finds,
    query_finds_nearby,
    insert_find,
    insert_find_images,
    get_find_by_id,
    update_find as db_update_find,
    delete_find as db_delete_find,
    query_clusters,
    ensure_user_profile,
    get_user_profile,
    update_user_profile,
)

load_dotenv()

DATA_SOURCE_MODE = os.getenv("DATA_SOURCE_MODE", "mock").lower()
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()


def _parse_cors_origins() -> List[str]:
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return [
            "http://localhost",
            "http://127.0.0.1",
            "https://forago.app",
        ]

    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or [
        "http://localhost",
        "http://127.0.0.1",
        "https://forago.app",
    ]


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
    allow_origins=_parse_cors_origins(),
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
    displayNickname: Optional[str] = None
    text: str
    createdAt: datetime

class PublicFindRecord(BaseModel):
    id: str
    userId: str
    displayNickname: Optional[str] = None
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


class UserProfileResponse(BaseModel):
    userId: str
    accountTier: str
    badge: Optional[str] = None
    lastActionAt: Optional[datetime] = None
    languageCode: str
    mapCenterLat: float
    mapCenterLng: float
    mapZoom: float
    defaultCategory: str
    displayNickname: str
    displayName: Optional[str] = None
    avatarUrl: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime
    badges: List[str] = []


class UpdateUserProfileRequest(BaseModel):
    displayNickname: Optional[str] = None
    displayName: Optional[str] = None
    avatarUrl: Optional[str] = None
    languageCode: Optional[str] = None
    mapCenterLat: Optional[float] = None
    mapCenterLng: Optional[float] = None
    mapZoom: Optional[float] = None
    defaultCategory: Optional[str] = None

    @field_validator("displayNickname")
    @classmethod
    def validate_display_nickname(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        if len(value) < 3:
            raise ValueError("displayNickname must be at least 3 characters")
        if len(value) > 40:
            raise ValueError("displayNickname must be at most 40 characters")
        return value

    @field_validator("languageCode")
    @classmethod
    def validate_language_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip().lower()
        allowed = {"sk", "cs", "en", "de", "pl", "hu"}
        if value not in allowed:
            raise ValueError(f"languageCode must be one of {sorted(allowed)}")
        return value

    @field_validator("mapZoom")
    @classmethod
    def validate_map_zoom(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v < 1 or v > 22:
            raise ValueError("mapZoom must be between 1 and 22")
        return v

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


class PresignFindImagesRequest(BaseModel):
    imageIds: List[str]


class PresignedFindImageUpload(BaseModel):
    imageId: str
    storageRef: str
    thumbnailUploadUrl: str
    fullUploadUrl: str
    thumbnailUrl: str
    fullUrl: str


class PresignFindImagesResponse(BaseModel):
    uploads: List[PresignedFindImageUpload]


class AttachFindImagesRequest(BaseModel):
    images: List[RecordImageRef]

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

MOCK_PROFILES = {
    "user_jan": {
        "userId": "user_jan",
        "accountTier": "free",
        "badge": None,
        "lastActionAt": datetime.now(),
        "languageCode": "sk",
        "mapCenterLat": 48.1486,
        "mapCenterLng": 17.1077,
        "mapZoom": 11.0,
        "defaultCategory": "nature/forest",
        "displayNickname": "jan",
        "displayName": "Jan",
        "avatarUrl": None,
        "createdAt": datetime.now(),
        "updatedAt": datetime.now(),
        "badges": [],
    }
}


def _derive_fallback_nickname(user_id: str, email: Optional[str]) -> str:
    if email:
        candidate = email.split("@", 1)[0].strip().lower()
        candidate = "".join(ch for ch in candidate if ch.isalnum() or ch in {"_", "-"})
        if len(candidate) >= 3:
            return candidate[:40]
    return f"user_{user_id.replace('-', '')[:8]}"


def _derive_fallback_display_name(email: Optional[str], nickname: str) -> str:
    if email:
        local = email.split("@", 1)[0].strip()
        if local:
            return local[:80]
    return nickname


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


@app.get("/api/profile", response_model=UserProfileResponse)
async def get_profile(current_user: AuthUser = Depends(get_current_user)):
    """Return authenticated user's editable profile and preferences."""
    try:
        if DATA_SOURCE_MODE == "db":
            claims = current_user.claims
            email_claim = claims.get("email")
            email = email_claim if isinstance(email_claim, str) else None

            nickname = _derive_fallback_nickname(current_user.user_id, email)
            display_name = _derive_fallback_display_name(email, nickname)

            profile = await get_user_profile(current_user.user_id)
            if profile is None:
                profile = await ensure_user_profile(
                    user_id=current_user.user_id,
                    fallback_nickname=nickname,
                    fallback_display_name=display_name,
                )
            return UserProfileResponse(**profile)

        if current_user.user_id not in MOCK_PROFILES:
            claims = current_user.claims
            email_claim = claims.get("email")
            email = email_claim if isinstance(email_claim, str) else None
            nickname = _derive_fallback_nickname(current_user.user_id, email)
            MOCK_PROFILES[current_user.user_id] = {
                "userId": current_user.user_id,
                "accountTier": "free",
                "badge": None,
                "lastActionAt": datetime.now(),
                "languageCode": "sk",
                "mapCenterLat": 48.1486,
                "mapCenterLng": 17.1077,
                "mapZoom": 11.0,
                "defaultCategory": "nature/forest",
                "displayNickname": nickname,
                "displayName": _derive_fallback_display_name(email, nickname),
                "avatarUrl": None,
                "createdAt": datetime.now(),
                "updatedAt": datetime.now(),
                "badges": [],
            }
        return UserProfileResponse(**MOCK_PROFILES[current_user.user_id])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load profile: {str(e)}")


@app.patch("/api/profile", response_model=UserProfileResponse)
async def patch_profile(
    request: UpdateUserProfileRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Update authenticated user's profile preferences."""
    try:
        if DATA_SOURCE_MODE == "db":
            updated = await update_user_profile(
                user_id=current_user.user_id,
                display_nickname=request.displayNickname,
                display_name=request.displayName,
                avatar_url=request.avatarUrl,
                language_code=request.languageCode,
                map_center_lat=request.mapCenterLat,
                map_center_lng=request.mapCenterLng,
                map_zoom=request.mapZoom,
                default_category=request.defaultCategory,
            )
            if updated is None:
                raise HTTPException(status_code=404, detail="Profile not found")
            return UserProfileResponse(**updated)

        if current_user.user_id not in MOCK_PROFILES:
            _ = await get_profile(current_user)

        profile = MOCK_PROFILES[current_user.user_id]
        updates = {
            "displayNickname": request.displayNickname,
            "displayName": request.displayName,
            "avatarUrl": request.avatarUrl,
            "languageCode": request.languageCode,
            "mapCenterLat": request.mapCenterLat,
            "mapCenterLng": request.mapCenterLng,
            "mapZoom": request.mapZoom,
            "defaultCategory": request.defaultCategory,
        }
        for key, value in updates.items():
            if value is not None:
                profile[key] = value
        profile["updatedAt"] = datetime.now()
        return UserProfileResponse(**profile)
    except HTTPException:
        raise
    except Exception as e:
        detail = str(e)
        if "ux_profiles_display_nickname_lower" in detail or "duplicate key" in detail.lower():
            raise HTTPException(status_code=409, detail="Display nickname is already in use")
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {detail}")

@app.get("/api/health")
async def health_check():
    """Health check - used by monitoring"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow(),
        "version": __version__,
        "dataSourceMode": DATA_SOURCE_MODE,
    }


@app.get("/api/version")
async def version_info():
    """Return backend version for debugging/monitoring"""
    return {
        "backend": __version__,
        "environment": ENVIRONMENT,
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


@app.post("/api/finds/{find_id}/images/presign", response_model=PresignFindImagesResponse)
async def presign_find_images(
    find_id: str,
    request: PresignFindImagesRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Create presigned R2 upload URLs for a user's find images."""
    if not request.imageIds:
        raise HTTPException(status_code=400, detail="At least one imageId is required")

    if len(request.imageIds) > 10:
        raise HTTPException(status_code=400, detail="Too many images requested")

    try:
        if DATA_SOURCE_MODE != "db":
            raise HTTPException(status_code=501, detail="Image uploads are only available in db mode")

        existing = await get_find_by_id(find_id, current_user.user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Find not found")

        if not is_r2_configured():
            raise HTTPException(status_code=503, detail="R2 storage is not configured")

        uploads = generate_find_image_upload_plans(
            user_id=current_user.user_id,
            find_id=find_id,
            image_ids=request.imageIds,
        )
        return PresignFindImagesResponse(
            uploads=[PresignedFindImageUpload(**item) for item in uploads]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create upload URLs: {str(e)}")


@app.post("/api/finds/{find_id}/images", response_model=List[RecordImageRef], status_code=status.HTTP_201_CREATED)
async def attach_find_images(
    find_id: str,
    request: AttachFindImagesRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Persist uploaded image metadata for an existing find."""
    if not request.images:
        raise HTTPException(status_code=400, detail="At least one image reference is required")

    try:
        if DATA_SOURCE_MODE != "db":
            raise HTTPException(status_code=501, detail="Image uploads are only available in db mode")

        existing = await get_find_by_id(find_id, current_user.user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Find not found")

        saved = await insert_find_images(
            find_id,
            [image.model_dump() for image in request.images],
        )
        return [RecordImageRef(**item) for item in saved]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save image metadata: {str(e)}")

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
