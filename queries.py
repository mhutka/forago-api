"""Database query helpers for ForaGo Backend."""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import json
from database import get_db_connection, release_db_connection


def _decode_jsonb(value: Any) -> List[Any]:
    """asyncpg may return JSONB columns as a raw JSON string; decode if needed."""
    if isinstance(value, str):
        return json.loads(value)
    return value if value is not None else []

# These models are imported from main.py to avoid circular imports
# We'll use them in responses


async def _fetch_images_and_comments(conn: Any, find_uuids: List[Any]) -> Tuple[Dict[str, list], Dict[str, list]]:
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
    comment_user_ids = [row["user_id"] for row in cmt_rows]
    comment_nicknames = await _fetch_display_nicknames(conn, comment_user_ids)

    images_by_id: Dict[str, list] = {}
    for r in img_rows:
        fid = str(r["find_id"])
        images_by_id.setdefault(fid, []).append({
            "thumbnailUrl": r["thumbnail_url"],
            "fullUrl": r["full_url"],
            "storageRef": r["storage_ref"],
        })

    comments_by_id: Dict[str, list] = {}
    for r in cmt_rows:
        fid = str(r["find_id"])
        comments_by_id.setdefault(fid, []).append({
            "id": str(r["id"]),
            "userId": str(r["user_id"]),
            "displayNickname": comment_nicknames.get(str(r["user_id"])),
            "text": r["text"],
            "createdAt": r["created_at"],
        })

    return images_by_id, comments_by_id


async def _fetch_display_nicknames(conn: Any, user_ids: List[Any]) -> Dict[str, str]:
    """Fetch display nicknames for a set of user UUIDs."""
    if not user_ids:
        return {}

    rows = await conn.fetch(
        "SELECT id, display_nickname FROM profiles WHERE id = ANY($1::uuid[])",
        user_ids,
    )
    return {str(row["id"]): row["display_nickname"] for row in rows}


def _apply_find_filters(
    query: str,
    params: List[Any],
    cluster: Optional[str],
    category: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    period: Optional[str],
) -> Tuple[str, List[Any]]:
    """Apply common filters used by public/private find queries."""
    if cluster:
        query += f" AND cluster_hash = ${len(params) + 1}"
        params.append(cluster)

    if from_date:
        query += f" AND date >= ${len(params) + 1}"
        params.append(from_date)

    if to_date:
        query += f" AND date <= ${len(params) + 1}"
        params.append(to_date)

    if category:
        segments = [seg for seg in category.split("/") if seg]
        if segments:
            query += f" AND category_paths @> ${len(params) + 1}::jsonb[]"
            params.append(json.dumps([segments]))

    if period:
        query += f" AND period = ${len(params) + 1}"
        params.append(period)

    return query, params


def _build_find_record(
    row: Any,
    fid: str,
    nicknames_by_user_id: Dict[str, str],
    images_by_id: Dict[str, list],
    comments_by_id: Dict[str, list],
    include_location: bool,
) -> Dict[str, Any]:
    """Build API record payload from a DB row."""
    payload: Dict[str, Any] = {
        "id": fid,
        "userId": str(row["user_id"]),
        "displayNickname": nicknames_by_user_id.get(str(row["user_id"])),
        "date": row["date"],
        "description": row["description"],
        "clusterHash": row["cluster_hash"],
        "categoryPaths": _decode_jsonb(row["category_paths"]),
        "period": row["period"],
        "images": images_by_id.get(fid, []),
        "comments": comments_by_id.get(fid, []),
    }

    if include_location:
        payload["location"] = {
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }

    return payload


async def query_public_finds(
    cluster: Optional[str] = None,
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
) -> List[dict]:
    """Query public finds with shared filters."""
    conn = await get_db_connection()
    try:
        query = """
            SELECT 
                id, user_id, date, description, cluster_hash,
                category_paths, period, created_at
            FROM finds
            WHERE allow_public = TRUE
        """
        params: List[Any] = []
        query, params = _apply_find_filters(
            query=query,
            params=params,
            cluster=cluster,
            category=category,
            from_date=from_date,
            to_date=to_date,
            period=period,
        )

        query += " ORDER BY date DESC"

        rows = await conn.fetch(query, *params)

        find_uuids = [row["id"] for row in rows]
        owner_ids = [row["user_id"] for row in rows]
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, find_uuids)
        nicknames_by_user_id = await _fetch_display_nicknames(conn, owner_ids)

        results = []
        for row in rows:
            fid = str(row["id"])
            results.append(
                _build_find_record(
                    row=row,
                    fid=fid,
                    nicknames_by_user_id=nicknames_by_user_id,
                    images_by_id=images_by_id,
                    comments_by_id=comments_by_id,
                    include_location=False,
                )
            )

        return results
    finally:
        await release_db_connection(conn)


async def query_private_finds(
    user_id: str,
    cluster: Optional[str] = None,
    category: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: Optional[str] = None,
) -> List[dict]:
    """Query private finds for a specific user with shared filters."""
    conn = await get_db_connection()
    try:
        query = """
            SELECT 
                id, user_id, date, description, cluster_hash,
                latitude, longitude, category_paths, period, created_at
            FROM finds
            WHERE user_id = $1
        """
        params: List[Any] = [user_id]
        query, params = _apply_find_filters(
            query=query,
            params=params,
            cluster=cluster,
            category=category,
            from_date=from_date,
            to_date=to_date,
            period=period,
        )

        query += " ORDER BY date DESC"

        rows = await conn.fetch(query, *params)

        find_uuids = [row["id"] for row in rows]
        owner_ids = [row["user_id"] for row in rows]
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, find_uuids)
        nicknames_by_user_id = await _fetch_display_nicknames(conn, owner_ids)

        results = []
        for row in rows:
            fid = str(row["id"])
            results.append(
                _build_find_record(
                    row=row,
                    fid=fid,
                    nicknames_by_user_id=nicknames_by_user_id,
                    images_by_id=images_by_id,
                    comments_by_id=comments_by_id,
                    include_location=True,
                )
            )

        return results
    finally:
        await release_db_connection(conn)


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
    """Insert a new find record into database and return API payload."""
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
        nicknames_by_user_id = await _fetch_display_nicknames(conn, [row["user_id"]])
        return _build_find_record(
            row=row,
            fid=fid,
            nicknames_by_user_id=nicknames_by_user_id,
            images_by_id=images_by_id,
            comments_by_id=comments_by_id,
            include_location=True,
        )
    finally:
        await release_db_connection(conn)


async def get_find_by_id(find_id: str, user_id: str) -> Optional[dict]:
    """Fetch a single find with images and comments by ID."""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, date, description, cluster_hash,
                   latitude, longitude, category_paths, period
            FROM finds WHERE id = $1::uuid AND user_id = $2::uuid
            """,
            find_id,
            user_id,
        )
        if row is None:
            return None

        fid = str(row["id"])
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, [row["id"]])
        nicknames_by_user_id = await _fetch_display_nicknames(conn, [row["user_id"]])
        return _build_find_record(
            row=row,
            fid=fid,
            nicknames_by_user_id=nicknames_by_user_id,
            images_by_id=images_by_id,
            comments_by_id=comments_by_id,
            include_location=True,
        )
    finally:
        await release_db_connection(conn)


async def get_user_profile(user_id: str) -> Optional[dict]:
    """Fetch profile data for a user including earned badge codes."""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT
                p.id,
                p.account_tier,
                p.badge,
                p.last_action_at,
                p.language_code,
                p.map_center_lat,
                p.map_center_lng,
                p.map_zoom,
                p.default_category,
                p.display_nickname,
                p.display_name,
                p.avatar_url,
                p.created_at,
                p.updated_at,
                COALESCE(
                    ARRAY_AGG(ub.badge_code) FILTER (WHERE ub.badge_code IS NOT NULL),
                    ARRAY[]::text[]
                ) AS badges
            FROM profiles p
            LEFT JOIN user_badges ub ON ub.user_id = p.id
            WHERE p.id = $1::uuid
            GROUP BY p.id
            """,
            user_id,
        )

        if row is None:
            return None

        return {
            "userId": str(row["id"]),
            "accountTier": row["account_tier"],
            "badge": row["badge"],
            "lastActionAt": row["last_action_at"],
            "languageCode": row["language_code"],
            "mapCenterLat": float(row["map_center_lat"]),
            "mapCenterLng": float(row["map_center_lng"]),
            "mapZoom": float(row["map_zoom"]),
            "defaultCategory": row["default_category"],
            "displayNickname": row["display_nickname"],
            "displayName": row["display_name"],
            "avatarUrl": row["avatar_url"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "badges": list(row["badges"] or []),
        }
    finally:
        await release_db_connection(conn)


async def ensure_user_profile(
    user_id: str,
    fallback_nickname: str,
    fallback_display_name: str,
    fallback_language_code: str = "sk",
) -> dict:
    """Ensure user has a profile row, then return profile payload."""
    conn = await get_db_connection()
    try:
        await conn.execute(
            """
            INSERT INTO profiles (
                id,
                display_nickname,
                display_name,
                language_code
            )
            VALUES ($1::uuid, $2, $3, $4)
            ON CONFLICT (id) DO NOTHING
            """,
            user_id,
            fallback_nickname,
            fallback_display_name,
            fallback_language_code,
        )
    finally:
        await release_db_connection(conn)

    profile = await get_user_profile(user_id)
    if profile is None:
        raise RuntimeError("Failed to load profile after ensure")
    return profile


async def update_user_profile(
    user_id: str,
    display_nickname: Optional[str] = None,
    display_name: Optional[str] = None,
    avatar_url: Optional[str] = None,
    language_code: Optional[str] = None,
    map_center_lat: Optional[float] = None,
    map_center_lng: Optional[float] = None,
    map_zoom: Optional[float] = None,
    default_category: Optional[str] = None,
) -> Optional[dict]:
    """Update editable profile fields for the given user."""
    conn = await get_db_connection()
    try:
        set_parts: List[str] = []
        params: List[Any] = []

        if display_nickname is not None:
            params.append(display_nickname)
            set_parts.append(f"display_nickname = ${len(params)}")
        if display_name is not None:
            params.append(display_name)
            set_parts.append(f"display_name = ${len(params)}")
        if avatar_url is not None:
            params.append(avatar_url)
            set_parts.append(f"avatar_url = ${len(params)}")
        if language_code is not None:
            params.append(language_code)
            set_parts.append(f"language_code = ${len(params)}")
        if map_center_lat is not None:
            params.append(map_center_lat)
            set_parts.append(f"map_center_lat = ${len(params)}")
        if map_center_lng is not None:
            params.append(map_center_lng)
            set_parts.append(f"map_center_lng = ${len(params)}")
        if map_zoom is not None:
            params.append(map_zoom)
            set_parts.append(f"map_zoom = ${len(params)}")
        if default_category is not None:
            params.append(default_category)
            set_parts.append(f"default_category = ${len(params)}")

        if set_parts:
            set_parts.append("updated_at = now()")
            params.append(user_id)
            await conn.execute(
                f"UPDATE profiles SET {', '.join(set_parts)} WHERE id = ${len(params)}::uuid",
                *params,
            )
    finally:
        await release_db_connection(conn)

    return await get_user_profile(user_id)


async def insert_find_images(find_id: str, images: List[dict]) -> List[dict]:
    """Persist uploaded image metadata for a find."""
    if not images:
        return []

    conn = await get_db_connection()
    try:
        async with conn.transaction():
            for image in images:
                await conn.execute(
                    """
                    INSERT INTO find_images (find_id, thumbnail_url, full_url, storage_ref)
                    VALUES ($1::uuid, $2, $3, $4)
                    """,
                    find_id,
                    image["thumbnailUrl"],
                    image["fullUrl"],
                    image.get("storageRef"),
                )
        return images
    finally:
        await release_db_connection(conn)


async def update_find(
    find_id: str,
    user_id: str,
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
        set_parts: List[str] = []
        params: List[Any] = []

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
            return await get_find_by_id(find_id, user_id)

        set_parts.append("updated_at = now()")
        params.append(find_id)
        params.append(user_id)

        query = f"""
            UPDATE finds SET {', '.join(set_parts)}
                        WHERE id = ${len(params) - 1}::uuid
                            AND user_id = ${len(params)}::uuid
            RETURNING id, user_id, date, description, cluster_hash,
                      latitude, longitude, category_paths, period
        """

        row = await conn.fetchrow(query, *params)
        if row is None:
            return None

        fid = str(row["id"])
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, [row["id"]])
        nicknames_by_user_id = await _fetch_display_nicknames(conn, [row["user_id"]])
        return _build_find_record(
            row=row,
            fid=fid,
            nicknames_by_user_id=nicknames_by_user_id,
            images_by_id=images_by_id,
            comments_by_id=comments_by_id,
            include_location=True,
        )
    finally:
        await release_db_connection(conn)


async def delete_find(find_id: str, user_id: str) -> bool:
    """Delete a find by ID. Returns True if a row was deleted."""
    conn = await get_db_connection()
    try:
        result = await conn.execute(
            "DELETE FROM finds WHERE id = $1::uuid AND user_id = $2::uuid", find_id, user_id
        )
        return result == "DELETE 1"
    finally:
        await release_db_connection(conn)


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
        params: List[Any] = []

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
            path_counts: Dict[str, int] = {}
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
        await release_db_connection(conn)
