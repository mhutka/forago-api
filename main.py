"""
ForaGo Backend - FastAPI + PostgreSQL
Main application file with routes and configuration.
"""

import logging
import logging.handlers
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from config import settings
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
    ensure_user_profile,
    get_user_profile,
    get_user_active_variant,
    list_top_categories,
    list_category_items,
    create_category_item,
    resolve_item_context,
    resolve_category_ids,
    update_user_profile,
    insert_find_comment,
)

# ============ LOGGING SETUP ============
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ============ CONFIG ============
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup application resources."""
    logger.info("🚀 ForaGo API starting up")
    logger.info("📖 Docs: http://localhost:8000/docs")
    logger.info("🔧 ReDoc: http://localhost:8000/redoc")
    logger.info("🗂️ Data source mode: %s", settings.data_source_mode)

    try:
        settings.validate_startup()
        validate_auth_configuration(is_production=settings.is_production())
    except Exception as e:
        logger.error("Startup validation failed: %s", e, exc_info=True)
        raise

    if settings.data_source_mode == "db":
        try:
            await init_db()
            await run_migrations()
            logger.info("✓ Database initialized and migrations applied")
        except Exception as e:
            logger.error("Database initialization failed: %s", e, exc_info=True)
            raise

    try:
        yield
    finally:
        if settings.data_source_mode == "db":
            try:
                await close_db()
                logger.info("✓ Database pool closed")
            except Exception as e:
                logger.error("Database shutdown error: %s", e, exc_info=True)


app = FastAPI(
    title="ForaGo API",
    version=__version__,
    description="Backend for ForaGo bushcraft app",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Middleware: CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_parsed_cors_origins(),
    allow_origin_regex=r"^https://([a-zA-Z0-9-]+\.)*forago\.pages\.dev$|^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware: Compression
app.add_middleware(GZipMiddleware, minimum_size=1000)

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


class CreateCommentRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Comment text must not be empty")
        if len(normalized) > 1000:
            raise ValueError("Comment text must be at most 1000 characters")
        return normalized

class PublicFindRecord(BaseModel):
    id: str
    userId: str
    displayNickname: Optional[str] = None
    date: datetime
    categoryPaths: List[List[str]]
    title: Optional[str] = None
    description: str
    clusterHash: str
    period: Optional[str] = None
    topCategorySlug: Optional[str] = None
    itemId: Optional[str] = None
    tagItemIds: List[str] = Field(default_factory=list)
    images: List[RecordImageRef] = Field(default_factory=list)
    comments: List[RecordComment] = Field(default_factory=list)

class PrivateFindRecord(PublicFindRecord):
    location: LatLng

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
    badges: List[str] = Field(default_factory=list)


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


class ActiveVariantResponse(BaseModel):
    id: str
    code: str
    displayName: str
    defaultLanguageCode: str
    defaultMapCenterLat: float
    defaultMapCenterLng: float
    defaultMapZoom: float
    topmenuIconSet: Dict[str, Any] = Field(default_factory=dict)
    themeTokens: Dict[str, Any] = Field(default_factory=dict)


class TopCategoryResponse(BaseModel):
    id: str
    slug: str
    iconKey: Optional[str] = None
    label: str
    sortOrder: int


class CategoryItemResponse(BaseModel):
    id: str
    categoryId: str
    categorySlug: str
    topCategorySlug: str
    topCategoryLabel: str
    canonicalKey: Optional[str] = None
    title: str
    descriptionText: Optional[str] = None
    imageUrl: Optional[str] = None
    ownerType: str
    approvalState: str
    promotedToAdmin: bool
    createdByUserId: str


class CreateCategoryItemRequest(BaseModel):
    topCategorySlug: str
    categorySlug: Optional[str] = None
    title: str
    descriptionText: Optional[str] = None

    @field_validator("topCategorySlug")
    @classmethod
    def validate_top_category_slug(cls, v: str) -> str:
        value = v.strip().lower()
        if len(value) < 2:
            raise ValueError("topCategorySlug must be at least 2 characters")
        return value

    @field_validator("categorySlug")
    @classmethod
    def validate_category_slug(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip().lower()
        return value or None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        value = v.strip()
        if len(value) < 2:
            raise ValueError("title must be at least 2 characters")
        if len(value) > 80:
            raise ValueError("title must be at most 80 characters")
        return value

    @field_validator("descriptionText")
    @classmethod
    def validate_description_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        return value or None

VALID_PERIODS = {
    "JAN_1", "JAN_2", "FEB_1", "FEB_2", "MAR_1", "MAR_2",
    "APR_1", "APR_2", "MAY_1", "MAY_2", "JUN_1", "JUN_2",
    "JUL_1", "JUL_2", "AUG_1", "AUG_2", "SEP_1", "SEP_2",
    "OCT_1", "OCT_2", "NOV_1", "NOV_2", "DEC_1", "DEC_2",
}


class CreateFindRequest(BaseModel):
    date: datetime
    categoryPaths: Optional[List[List[str]]] = None
    title: Optional[str] = None
    description: str
    location: LatLng
    clusterHash: str
    itemId: Optional[str] = None
    tagItemIds: Optional[List[str]] = None
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
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[LatLng] = None
    itemId: Optional[str] = None
    tagItemIds: Optional[List[str]] = None
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


def _normalize_tag_item_ids(tag_item_ids: Optional[List[str]], item_id: Optional[str]) -> List[str]:
    """Merge legacy primary item and new tag items into a deduplicated list."""
    normalized: List[str] = []
    seen = set()

    for candidate in ([item_id] if item_id is not None else []) + list(tag_item_ids or []):
        value = candidate.strip() if isinstance(candidate, str) else ""
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    return normalized


async def _resolve_tag_item_contexts(
    *,
    user_id: str,
    app_variant_id: str,
    language_code: str,
    tag_item_ids: List[str],
) -> List[Dict[str, Any]]:
    """Resolve all requested tag items and return their category contexts."""
    contexts: List[Dict[str, Any]] = []

    for tag_item_id in tag_item_ids:
        item_context = await resolve_item_context(
            user_id=user_id,
            app_variant_id=app_variant_id,
            item_id=tag_item_id,
            language_code=language_code,
        )
        if item_context is None:
            raise HTTPException(status_code=400, detail="Invalid or inaccessible itemId")
        contexts.append(item_context)

    return contexts


def _category_slugs_from_paths(category_paths: Optional[List[List[str]]]) -> List[str]:
    """Extract unique top-level slugs from client-provided category paths."""
    slugs: List[str] = []
    for path in category_paths or []:
        if not path or not isinstance(path[0], str):
            continue
        slug = path[0].strip().lower()
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs

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
    """Derive a fallback display nickname from user_id or email."""
    if email:
        candidate = email.split("@", 1)[0].strip().lower()
        candidate = "".join(ch for ch in candidate if ch.isalnum() or ch in {"_", "-"})
        if len(candidate) >= 3:
            return candidate[:40]
    return f"user_{user_id.replace('-', '')[:8]}"


def _derive_fallback_display_name(email: Optional[str], nickname: str) -> str:
    """Derive a fallback display name from email or nickname."""
    if email:
        local = email.split("@", 1)[0].strip()
        if local:
            return local[:80]
    return nickname


def _public_records_from_mock() -> List["PublicFindRecord"]:
    """Get all public finds from mock data."""
    return [
        find
        for find in MOCK_FINDS.values()
        if isinstance(find, PublicFindRecord)
        and not isinstance(find, PrivateFindRecord)
    ]


def _private_records_from_mock() -> List["PrivateFindRecord"]:
    """Get all private finds from mock data for current user."""
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


def _matches_period_filter(
    record: PublicFindRecord,
    period: Optional[str],
    periods: Optional[List[str]] = None,
) -> bool:
    effective_periods = set(([period] if period else []) + list(periods or []))
    if not effective_periods:
        return True
    return record.period in effective_periods


def _validate_filter_periods(period: Optional[str], periods: Optional[List[str]]) -> None:
    invalid_periods = {
        value for value in ([period] if period else []) + list(periods or [])
        if value not in VALID_PERIODS
    }
    if invalid_periods:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period filter: {sorted(invalid_periods)}",
        )


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
        if settings.data_source_mode == "db":
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
        if settings.data_source_mode == "db":
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
        "dataSourceMode": settings.data_source_mode,
    }


@app.get("/api/version")
async def version_info():
    """Return backend version for debugging/monitoring"""
    return {
        "backend": __version__,
        "environment": settings.environment,
        "dataSourceMode": settings.data_source_mode,
    }


@app.get("/api/variants/active", response_model=ActiveVariantResponse)
async def get_active_variant(current_user: AuthUser = Depends(get_current_user)):
    """Return active/default variant context for authenticated user."""
    try:
        if settings.data_source_mode != "db":
            return ActiveVariantResponse(
                id="mock-variant-sk",
                code="forago-sk",
                displayName="ForaGo SK",
                defaultLanguageCode="sk",
                defaultMapCenterLat=48.1486,
                defaultMapCenterLng=17.1077,
                defaultMapZoom=11.0,
                topmenuIconSet={
                    "topCategories": [
                        {"slug": "mushrooms", "iconKey": "mushroom"},
                        {"slug": "herbs", "iconKey": "leaf"},
                        {"slug": "birds", "iconKey": "bird"},
                        {"slug": "fish", "iconKey": "fish"},
                        {"slug": "butterflies", "iconKey": "butterfly"},
                        {"slug": "insects", "iconKey": "insect"},
                    ]
                },
                themeTokens={"primaryColor": "#2D6A4F", "radiusScale": 1.0},
            )

        variant = await get_user_active_variant(current_user.user_id)
        if variant is None:
            raise HTTPException(status_code=404, detail="No active variant found for user")
        return ActiveVariantResponse(**variant)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load active variant: {str(e)}")


@app.get("/api/categories/top", response_model=List[TopCategoryResponse])
async def get_top_categories(current_user: AuthUser = Depends(get_current_user)):
    """Return top-level categories for active user variant."""
    try:
        if settings.data_source_mode != "db":
            return [
                TopCategoryResponse(id="mock-mushrooms", slug="mushrooms", iconKey="mushroom", label="Huby", sortOrder=10),
                TopCategoryResponse(id="mock-herbs", slug="herbs", iconKey="leaf", label="Bylinky", sortOrder=20),
                TopCategoryResponse(id="mock-birds", slug="birds", iconKey="bird", label="Vtaky", sortOrder=30),
                TopCategoryResponse(id="mock-fish", slug="fish", iconKey="fish", label="Ryby", sortOrder=40),
                TopCategoryResponse(id="mock-butterflies", slug="butterflies", iconKey="butterfly", label="Motyle", sortOrder=50),
                TopCategoryResponse(id="mock-insects", slug="insects", iconKey="insect", label="Hmyz", sortOrder=60),
            ]

        variant = await get_user_active_variant(current_user.user_id)
        if variant is None:
            raise HTTPException(status_code=404, detail="No active variant found for user")

        profile = await get_user_profile(current_user.user_id)
        language_code = (profile or {}).get("languageCode") or variant["defaultLanguageCode"]
        rows = await list_top_categories(variant["id"], language_code)
        return [TopCategoryResponse(**row) for row in rows]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load categories: {str(e)}")


@app.get("/api/category-items", response_model=List[CategoryItemResponse])
async def get_category_items(
    topCategorySlug: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    current_user: AuthUser = Depends(get_current_user),
):
    """Single feed of category items: admin + approved + own (visible)."""
    try:
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be >= 0")

        if settings.data_source_mode != "db":
            return []

        variant = await get_user_active_variant(current_user.user_id)
        if variant is None:
            raise HTTPException(status_code=404, detail="No active variant found for user")

        profile = await get_user_profile(current_user.user_id)
        language_code = (profile or {}).get("languageCode") or variant["defaultLanguageCode"]

        rows = await list_category_items(
            user_id=current_user.user_id,
            app_variant_id=variant["id"],
            language_code=language_code,
            top_category_slug=topCategorySlug,
            q=q,
            limit=limit,
            offset=offset,
        )
        return [CategoryItemResponse(**row) for row in rows]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load category items: {str(e)}")


@app.post("/api/category-items", response_model=CategoryItemResponse, status_code=status.HTTP_201_CREATED)
async def post_category_item(
    request: CreateCategoryItemRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Create user-owned category item for active variant and return normalized item payload."""
    try:
        if settings.data_source_mode != "db":
            raise HTTPException(status_code=501, detail="category_item_error_create_unavailable_mock")

        variant = await get_user_active_variant(current_user.user_id)
        if variant is None:
            raise HTTPException(status_code=404, detail="No active variant found for user")

        profile = await get_user_profile(current_user.user_id)
        language_code = (profile or {}).get("languageCode") or variant["defaultLanguageCode"]
        category_slug = request.categorySlug or request.topCategorySlug

        row = await create_category_item(
            user_id=current_user.user_id,
            app_variant_id=variant["id"],
            language_code=language_code,
            top_category_slug=request.topCategorySlug,
            category_slug=category_slug,
            title=request.title,
            description_text=request.descriptionText,
        )
        return CategoryItemResponse(**row)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create category item: {str(e)}")

# ---------- FINDS ENDPOINTS ----------

@app.get("/api/finds/public", response_model=List[PublicFindRecord])
async def get_public_finds(
    cluster: Optional[str] = None,
    category: Optional[str] = None,
    topCategorySlug: Optional[str] = None,
    itemId: Optional[str] = None,
    tagItemIds: Optional[List[str]] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
    periods: Optional[List[str]] = None,
):
    """
    Get all public finds (visible to all users)
    Filter by cluster, category, date range, period
    """
    try:
        _validate_filter_periods(period, periods)
        if settings.data_source_mode == "db":
            results_data = await query_public_finds(
                cluster=cluster,
                category=category,
                top_category_slug=topCategorySlug,
                item_id=itemId,
                tag_item_ids=tagItemIds,
                from_date=from_date,
                to_date=to_date,
                period=period,
                periods=periods,
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

            if period or periods:
                results = [f for f in results if _matches_period_filter(f, period, periods)]

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
    topCategorySlug: Optional[str] = None,
    itemId: Optional[str] = None,
    tagItemIds: Optional[List[str]] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
    periods: Optional[List[str]] = None,
):
    """Get finds near a specific cluster"""
    try:
        _validate_filter_periods(period, periods)
        if settings.data_source_mode == "db":
            results_data = await query_finds_nearby(
                cluster=cluster,
                category=category,
                top_category_slug=topCategorySlug,
                item_id=itemId,
                tag_item_ids=tagItemIds,
                from_date=from_date,
                to_date=to_date,
                period=period,
                periods=periods,
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

            if period or periods:
                results = [f for f in results if _matches_period_filter(f, period, periods)]

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
    topCategorySlug: Optional[str] = None,
    itemId: Optional[str] = None,
    tagItemIds: Optional[List[str]] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
    periods: Optional[List[str]] = None,
    current_user: AuthUser = Depends(get_current_user),
):
    """
    Get current user's private finds
    Requires authentication
    """
    try:
        _validate_filter_periods(period, periods)
        effective_user_id = current_user.user_id

        if settings.data_source_mode == "db":
            results_data = await query_private_finds(
                user_id=effective_user_id,
                cluster=cluster,
                category=category,
                top_category_slug=topCategorySlug,
                item_id=itemId,
                tag_item_ids=tagItemIds,
                from_date=from_date,
                to_date=to_date,
                period=period,
                periods=periods,
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

            if period or periods:
                results = [f for f in results if _matches_period_filter(f, period, periods)]

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

        if settings.data_source_mode == "db":
            tag_item_ids = _normalize_tag_item_ids(request.tagItemIds, request.itemId)
            if not tag_item_ids:
                raise HTTPException(status_code=400, detail="At least one tag item is required. Use the 'unknown' item when needed.")

            variant = await get_user_active_variant(effective_user_id)
            if variant is None:
                raise HTTPException(status_code=404, detail="No active variant found for user")

            profile = await get_user_profile(effective_user_id)
            language_code = (profile or {}).get("languageCode") or variant["defaultLanguageCode"]
            item_contexts = await _resolve_tag_item_contexts(
                user_id=effective_user_id,
                app_variant_id=variant["id"],
                language_code=language_code,
                tag_item_ids=tag_item_ids,
            )
            primary_item_id = request.itemId or item_contexts[0]["itemId"]
            derived_category_ids = [context["categoryId"] for context in item_contexts]
            category_slugs = _category_slugs_from_paths(request.categoryPaths)
            explicit_category_ids = await resolve_category_ids(
                variant["id"], category_slugs,
            )
            if len(explicit_category_ids) != len(category_slugs):
                raise HTTPException(status_code=400, detail="Invalid category path")
            category_ids = list(dict.fromkeys(explicit_category_ids + derived_category_ids))

            result_data = await insert_find(
                user_id=effective_user_id,
                app_variant_id=variant["id"],
                date=request.date,
                title=request.title,
                description=request.description,
                cluster_hash=request.clusterHash,
                latitude=request.location.latitude,
                longitude=request.location.longitude,
                category_ids=category_ids,
                period=request.period,
                find_item_id=primary_item_id,
                tag_item_ids=tag_item_ids,
            )
            return PrivateFindRecord(**result_data)
        else:
            # Mock mode
            new_find = PrivateFindRecord(
                id=f"rec_{len(MOCK_FINDS) + 1:03d}",
                userId=effective_user_id,
                date=request.date,
                categoryPaths=request.categoryPaths or [],
                title=request.title,
                description=request.description,
                clusterHash=request.clusterHash,
                location=request.location,
                itemId=request.itemId,
                tagItemIds=_normalize_tag_item_ids(request.tagItemIds, request.itemId),
                period=request.period,
            )
            MOCK_FINDS[new_find.id] = new_find
            return new_find
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create find: {str(e)}",
        )

@app.get("/api/finds/{find_id}", response_model=PrivateFindRecord)
async def get_find(find_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Get find by ID (if user has access)"""
    try:
        if settings.data_source_mode == "db":
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


@app.post(
    "/api/finds/{find_id}/comments",
    response_model=RecordComment,
    status_code=status.HTTP_201_CREATED,
)
async def create_find_comment(
    find_id: str,
    request: CreateCommentRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Add a comment to a publicly visible find."""
    try:
        if settings.data_source_mode != "db":
            raise HTTPException(
                status_code=501,
                detail="Comments are only available in db mode",
            )

        comment = await insert_find_comment(
            find_id=find_id,
            user_id=current_user.user_id,
            text=request.text,
        )
        if comment is None:
            raise HTTPException(status_code=404, detail="Find not found")
        return RecordComment(**comment)
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail="Find not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create comment: {str(e)}")


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
        if settings.data_source_mode != "db":
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
        if settings.data_source_mode != "db":
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
        if settings.data_source_mode == "db":
            item_context = None
            find_item_id = None
            tag_item_ids = None
            # Category paths are validated against the active app variant;
            # tag-derived categories are retained for older clients.
            category_ids = None

            if (
                request.itemId is not None
                or request.tagItemIds is not None
                or request.categoryPaths is not None
            ):
                variant = await get_user_active_variant(current_user.user_id)
                if variant is None:
                    raise HTTPException(status_code=404, detail="No active variant found for user")
                profile = await get_user_profile(current_user.user_id)
                language_code = (profile or {}).get("languageCode") or variant["defaultLanguageCode"]
                item_contexts = []
                if request.itemId is not None or request.tagItemIds is not None:
                    tag_item_ids = _normalize_tag_item_ids(request.tagItemIds, request.itemId)
                    if not tag_item_ids:
                        raise HTTPException(status_code=400, detail="At least one tag item is required when updating item tags")
                    item_contexts = await _resolve_tag_item_contexts(
                        user_id=current_user.user_id,
                        app_variant_id=variant["id"],
                        language_code=language_code,
                        tag_item_ids=tag_item_ids,
                    )
                    item_context = item_contexts[0]
                    find_item_id = request.itemId or item_context["itemId"]
                derived_category_ids = [context["categoryId"] for context in item_contexts]
                category_slugs = _category_slugs_from_paths(request.categoryPaths)
                explicit_category_ids = await resolve_category_ids(
                    variant["id"], category_slugs,
                )
                if len(explicit_category_ids) != len(category_slugs):
                    raise HTTPException(status_code=400, detail="Invalid category path")
                category_ids = list(dict.fromkeys(explicit_category_ids + derived_category_ids))

            result = await db_update_find(
                find_id=find_id,
                user_id=current_user.user_id,
                date=request.date,
                title=request.title,
                description=request.description,
                latitude=request.location.latitude if request.location else None,
                longitude=request.location.longitude if request.location else None,
                category_ids=category_ids,
                period=request.period,
                find_item_id=find_item_id,
                tag_item_ids=tag_item_ids,
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
                    "title": request.title,
                    "description": request.description,
                    "location": request.location,
                    "itemId": request.itemId,
                    "tagItemIds": _normalize_tag_item_ids(request.tagItemIds, request.itemId) if request.itemId is not None or request.tagItemIds is not None else existing.tagItemIds,
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
        if settings.data_source_mode == "db":
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

# ============ ERROR HANDLERS ============

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom error response"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status": exc.status_code,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
