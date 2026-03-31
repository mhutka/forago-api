"""
Database query helpers for ForaGo Backend
"""

from typing import List, Optional
from datetime import datetime
import json
from database import get_db_connection
from pydantic import BaseModel


def _decode_jsonb(value):
    """asyncpg may return JSONB columns as a raw JSON string; decode if needed."""
    if isinstance(value, str):
        return json.loads(value)
    return value if value is not None else []

# These models are imported from main.py to avoid circular imports
# We'll use them in responses


async def _fetch_images_and_comments(conn, find_uuids: list):
    """Batch-fetch images and comments for a list of find UUID objects."""
    if not find_uuids:
        return {}, {}

    img_rows = await conn.fetch(
        "SELECT find_id, thumbnail_url, full_url, storage_ref "
        "FROM find_images WHERE find_id = ANY($1::uuid[])",
        find_uuids,
    )
    cmt_rows = await conn.fetch(
        "SELECT id, find_id, user_id, text, created_at "
        "FROM find_comments WHERE find_id = ANY($1::uuid[]) ORDER BY created_at ASC",
        find_uuids,
    )

    images_by_id: dict = {}
    for r in img_rows:
        fid = str(r["find_id"])
        images_by_id.setdefault(fid, []).append({
            "thumbnailUrl": r["thumbnail_url"],
            "fullUrl": r["full_url"],
            "storageRef": r["storage_ref"],
        })

    comments_by_id: dict = {}
    for r in cmt_rows:
        fid = str(r["find_id"])
        comments_by_id.setdefault(fid, []).append({
            "id": str(r["id"]),
            "userId": str(r["user_id"]),
            "text": r["text"],
            "createdAt": r["created_at"],
        })

    return images_by_id, comments_by_id


async def query_public_finds(
    cluster: Optional[str] = None,
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
) -> List[dict]:
    """
    Query public finds from database
    Returns list of dicts that can be converted to PublicFindRecord
    """
    conn = await get_db_connection()
    try:
        query = """
            SELECT 
                id, user_id, date, description, cluster_hash,
                category_paths, period, created_at
            FROM finds
            WHERE allow_public = TRUE
        """
        params = []
        
        if cluster:
            query += " AND cluster_hash = $" + str(len(params) + 1)
            params.append(cluster)
        
        if from_date:
            query += " AND date >= $" + str(len(params) + 1)
            params.append(from_date)
        
        if to_date:
            query += " AND date <= $" + str(len(params) + 1)
            params.append(to_date)
        
        # Category filter: category_paths contains the segments
        if category:
            segments = [seg for seg in category.split("/") if seg]
            if segments:
                # JSONB array contains any subarray with those segments
                query += " AND category_paths @> $" + str(len(params) + 1) + "::jsonb[]"
                params.append(json.dumps([segments]))

        if period:
            query += " AND period = $" + str(len(params) + 1)
            params.append(period)

        query += " ORDER BY date DESC"

        rows = await conn.fetch(query, *params)

        find_uuids = [row["id"] for row in rows]
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, find_uuids)

        results = []
        for row in rows:
            fid = str(row["id"])
            results.append({
                "id": fid,
                "userId": str(row["user_id"]),
                "date": row["date"],
                "description": row["description"],
                "clusterHash": row["cluster_hash"],
                "categoryPaths": _decode_jsonb(row["category_paths"]),
                "period": row["period"],
                "images": images_by_id.get(fid, []),
                "comments": comments_by_id.get(fid, []),
            })

        return results
    finally:
        await conn.close()


async def query_private_finds(
    user_id: str,
    cluster: Optional[str] = None,
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
) -> List[dict]:
    """
    Query private finds for a specific user from database
    """
    conn = await get_db_connection()
    try:
        query = """
            SELECT 
                id, user_id, date, description, cluster_hash,
                latitude, longitude, category_paths, period, created_at
            FROM finds
            WHERE user_id = $1
        """
        params = [user_id]
        
        if cluster:
            query += " AND cluster_hash = $" + str(len(params) + 1)
            params.append(cluster)
        
        if from_date:
            query += " AND date >= $" + str(len(params) + 1)
            params.append(from_date)
        
        if to_date:
            query += " AND date <= $" + str(len(params) + 1)
            params.append(to_date)
        
        # Category filter
        if category:
            segments = [seg for seg in category.split("/") if seg]
            if segments:
                query += " AND category_paths @> $" + str(len(params) + 1) + "::jsonb[]"
                params.append(json.dumps([segments]))

        if period:
            query += " AND period = $" + str(len(params) + 1)
            params.append(period)

        query += " ORDER BY date DESC"

        rows = await conn.fetch(query, *params)

        find_uuids = [row["id"] for row in rows]
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, find_uuids)

        results = []
        for row in rows:
            fid = str(row["id"])
            results.append({
                "id": fid,
                "userId": str(row["user_id"]),
                "date": row["date"],
                "description": row["description"],
                "clusterHash": row["cluster_hash"],
                "categoryPaths": _decode_jsonb(row["category_paths"]),
                "period": row["period"],
                "images": images_by_id.get(fid, []),
                "comments": comments_by_id.get(fid, []),
                "location": {
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                },
            })

        return results
    finally:
        await conn.close()


async def query_finds_nearby(
    cluster: str,
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
) -> List[dict]:
    """
    Query finds in a specific cluster (public view, no exact location)
    """
    return await query_public_finds(
        cluster=cluster,
        category=category,
        from_date=from_date,
        to_date=to_date,
        period=period,
    )


async def insert_find(
    user_id: str,
    date: datetime,
    description: str,
    cluster_hash: str,
    latitude: float,
    longitude: float,
    category_paths: List[List[str]],
    period: Optional[str] = None,
) -> dict:
    """
    Insert new find record into database
    Returns dict representation of PrivateFindRecord
    """
    conn = await get_db_connection()
    try:
        query = """
            INSERT INTO finds (
                user_id, date, description, cluster_hash,
                latitude, longitude, category_paths, period
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, user_id, date, description, cluster_hash,
                      latitude, longitude, category_paths, period, created_at
        """

        row = await conn.fetchrow(
            query,
            user_id,
            date,
            description,
            cluster_hash,
            latitude,
            longitude,
            json.dumps(category_paths),
            period,
        )

        fid = str(row["id"])
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, [row["id"]])
        return {
            "id": fid,
            "userId": str(row["user_id"]),
            "date": row["date"],
            "description": row["description"],
            "clusterHash": row["cluster_hash"],
            "categoryPaths": _decode_jsonb(row["category_paths"]),
            "period": row["period"],
            "images": images_by_id.get(fid, []),
            "comments": comments_by_id.get(fid, []),
            "location": {
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            },
        }
    finally:
        await conn.close()


async def get_find_by_id(find_id: str) -> Optional[dict]:
    """Fetch a single find with images and comments by ID."""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, date, description, cluster_hash,
                   latitude, longitude, category_paths, period
            FROM finds WHERE id = $1::uuid
            """,
            find_id,
        )
        if row is None:
            return None

        fid = str(row["id"])
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, [row["id"]])
        return {
            "id": fid,
            "userId": str(row["user_id"]),
            "date": row["date"],
            "description": row["description"],
            "clusterHash": row["cluster_hash"],
            "categoryPaths": _decode_jsonb(row["category_paths"]),
            "period": row["period"],
            "images": images_by_id.get(fid, []),
            "comments": comments_by_id.get(fid, []),
            "location": {
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            },
        }
    finally:
        await conn.close()


async def update_find(
    find_id: str,
    date: Optional[datetime] = None,
    description: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    category_paths: Optional[List[List[str]]] = None,
    period: Optional[str] = None,
) -> Optional[dict]:
    """Update mutable fields of a find. Returns None if find does not exist."""
    conn = await get_db_connection()
    try:
        set_parts = []
        params: list = []

        if date is not None:
            params.append(date)
            set_parts.append(f"date = ${len(params)}")
        if description is not None:
            params.append(description)
            set_parts.append(f"description = ${len(params)}")
        if latitude is not None:
            params.append(latitude)
            set_parts.append(f"latitude = ${len(params)}")
        if longitude is not None:
            params.append(longitude)
            set_parts.append(f"longitude = ${len(params)}")
        if category_paths is not None:
            params.append(json.dumps(category_paths))
            set_parts.append(f"category_paths = ${len(params)}")
        if period is not None:
            params.append(period)
            set_parts.append(f"period = ${len(params)}")

        if not set_parts:
            return await get_find_by_id(find_id)

        set_parts.append("updated_at = now()")
        params.append(find_id)

        query = f"""
            UPDATE finds SET {', '.join(set_parts)}
            WHERE id = ${len(params)}::uuid
            RETURNING id, user_id, date, description, cluster_hash,
                      latitude, longitude, category_paths, period
        """

        row = await conn.fetchrow(query, *params)
        if row is None:
            return None

        fid = str(row["id"])
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, [row["id"]])
        return {
            "id": fid,
            "userId": str(row["user_id"]),
            "date": row["date"],
            "description": row["description"],
            "clusterHash": row["cluster_hash"],
            "categoryPaths": _decode_jsonb(row["category_paths"]),
            "period": row["period"],
            "images": images_by_id.get(fid, []),
            "comments": comments_by_id.get(fid, []),
            "location": {
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            },
        }
    finally:
        await conn.close()


async def delete_find(find_id: str) -> bool:
    """Delete a find by ID. Returns True if a row was deleted."""
    conn = await get_db_connection()
    try:
        result = await conn.execute(
            "DELETE FROM finds WHERE id = $1::uuid", find_id
        )
        return result == "DELETE 1"
    finally:
        await conn.close()


async def query_clusters(
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> List[dict]:
    """Aggregate public finds into cluster summary records."""
    conn = await get_db_connection()
    try:
        sql = """
            SELECT
                cluster_hash,
                COUNT(*) AS total_records,
                MAX(updated_at) AS last_updated,
                jsonb_agg(category_paths) AS all_paths
            FROM finds
            WHERE allow_public = TRUE
        """
        params: list = []

        if from_date is not None:
            params.append(from_date)
            sql += f" AND date >= ${len(params)}"
        if to_date is not None:
            params.append(to_date)
            sql += f" AND date <= ${len(params)}"

        sql += " GROUP BY cluster_hash ORDER BY cluster_hash"

        rows = await conn.fetch(sql, *params)

        category_segments = [s for s in category.split("/") if s] if category else []

        results = []
        for row in rows:
            path_counts: dict = {}
            for find_paths in (row["all_paths"] or []):
                if find_paths:
                    for path in find_paths:
                        key = "/".join(path)
                        path_counts[key] = path_counts.get(key, 0) + 1

            if category_segments:
                prefix = "/".join(category_segments)
                if not any(k == prefix or k.startswith(prefix + "/") for k in path_counts):
                    continue

            results.append({
                "clusterHash": row["cluster_hash"],
                "categoryPathCounts": path_counts,
                "totalRecords": row["total_records"],
                "lastUpdated": row["last_updated"],
            })

        return results
    finally:
        await conn.close()
