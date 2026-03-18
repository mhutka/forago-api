"""
ForaGo Backend - FastAPI + PostgreSQL
Main application file with routes
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

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
        "http://localhost:*",
        "https://forago.app",
        "https://*.forago.pages.dev",
    ],
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
    images: List[RecordImageRef] = []
    comments: List[RecordComment] = []

class PrivateFindRecord(PublicFindRecord):
    location: LatLng

class PublicClusterRecord(BaseModel):
    clusterHash: str
    categoryPathCounts: dict
    totalRecords: int
    lastUpdated: datetime

class CreateFindRequest(BaseModel):
    date: datetime
    categoryPaths: List[List[str]]
    description: str
    location: LatLng
    clusterHash: str

class UpdateFindRequest(BaseModel):
    date: Optional[datetime] = None
    categoryPaths: Optional[List[List[str]]] = None
    description: Optional[str] = None
    location: Optional[LatLng] = None

# ============ MOCK DATA (temporary) ============
MOCK_FINDS = {
    "rec_001": PrivateFindRecord(
        id="rec_001",
        userId="user_jan",
        date=datetime.now(),
        categoryPaths=[["nature", "forest", "tree"]],
        description="Tall oak tree near village",
        clusterHash="51.5_-0.1",
        location=LatLng(latitude=51.5, longitude=-0.1),
    ),
    "rec_002": PublicFindRecord(
        id="rec_002",
        userId="user_maria",
        date=datetime.now(),
        categoryPaths=[["edible", "mushroom", "porcini"]],
        description="Porcini mushrooms found",
        clusterHash="51.5_-0.1",
    ),
}

# ============ ROUTES ============

@app.get("/api/health")
async def health_check():
    """Health check - used by monitoring"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow(),
        "version": "1.0.0"
    }

# ---------- FINDS ENDPOINTS ----------

@app.get("/api/finds/public", response_model=List[PublicFindRecord])
async def get_public_finds(
    cluster: Optional[str] = None,
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
):
    """
    Get all public finds (visible to all users)
    Filter by cluster, category, date range
    """
    # TODO: Query from PostgreSQL
    # For now: return mock data filtered
    results = [
        find for find in MOCK_FINDS.values()
        if isinstance(find, PublicFindRecord)
    ]
    
    if cluster:
        results = [f for f in results if f.clusterHash == cluster]
    
    return results

@app.get("/api/finds/nearby", response_model=List[PublicFindRecord])
async def get_finds_nearby(
    cluster: str,
    category: Optional[str] = None,
):
    """Get finds near a specific cluster"""
    results = [
        find for find in MOCK_FINDS.values()
        if isinstance(find, PublicFindRecord) and find.clusterHash == cluster
    ]
    return results

@app.get("/api/finds/private", response_model=List[PrivateFindRecord])
async def get_private_finds(
    # TODO: Add JWT validation
    # current_user: str = Depends(get_current_user)
):
    """
    Get current user's private finds
    Requires authentication
    """
    # TODO: Filter by current_user.id
    results = [
        find for find in MOCK_FINDS.values()
        if isinstance(find, PrivateFindRecord)
    ]
    return results

@app.post("/api/finds", response_model=PrivateFindRecord, status_code=status.HTTP_201_CREATED)
async def create_find(
    request: CreateFindRequest,
    # TODO: current_user: str = Depends(get_current_user)
):
    """
    Create new find record
    Returns PrivateFindRecord with exact location
    """
    # TODO: Save to PostgreSQL
    # For now: return mock
    new_find = PrivateFindRecord(
        id=f"rec_{len(MOCK_FINDS) + 1:03d}",
        userId="user_current",  # TODO: from JWT token
        date=request.date,
        categoryPaths=request.categoryPaths,
        description=request.description,
        clusterHash=request.clusterHash,
        location=request.location,
    )
    MOCK_FINDS[new_find.id] = new_find
    return new_find

@app.get("/api/finds/{find_id}", response_model=PrivateFindRecord)
async def get_find(find_id: str):
    """Get find by ID (if user has access)"""
    if find_id not in MOCK_FINDS:
        raise HTTPException(status_code=404, detail="Find not found")
    
    record = MOCK_FINDS[find_id]
    if isinstance(record, PrivateFindRecord):
        return record
    
    raise HTTPException(status_code=403, detail="Access denied")

@app.put("/api/finds/{find_id}", response_model=PrivateFindRecord)
async def update_find(
    find_id: str,
    request: UpdateFindRequest,
    # TODO: current_user: str = Depends(get_current_user)
):
    """Update find"""
    if find_id not in MOCK_FINDS:
        raise HTTPException(status_code=404, detail="Find not found")
    
    # TODO: Check if current_user owns this find
    # TODO: Update in PostgreSQL
    
    return MOCK_FINDS[find_id]

@app.delete("/api/finds/{find_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_find(find_id: str):
    """Delete find"""
    if find_id not in MOCK_FINDS:
        raise HTTPException(status_code=404, detail="Find not found")
    
    # TODO: Check if current_user owns this find
    # TODO: Delete from PostgreSQL
    del MOCK_FINDS[find_id]

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
    # TODO: Query from PostgreSQL (GROUP BY cluster_hash)
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

# ============ ERROR HANDLERS ============

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom error response"""
    return {
        "error": exc.detail,
        "status": exc.status_code,
        "timestamp": datetime.utcnow(),
    }

# ============ STARTUP ============

@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    print("🚀 ForaGo API started")
    print(f"📖 Docs: http://localhost:8000/docs")
    print(f"🔧 ReDoc: http://localhost:8000/redoc")
    # TODO: Connect to PostgreSQL
    # TODO: Run migrations

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
