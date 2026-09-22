"""Database query helpers for ForaGo Backend."""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import re
from database import get_db_connection, release_db_connection


def _period_for_date(value: datetime) -> str:
    """Return the persisted half-month period code for a find date."""
    month_codes = (
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
        "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    )
    return f"{month_codes[value.month - 1]}_{1 if value.day <= 15 else 2}"

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


async def _fetch_find_tag_item_ids(conn: Any, find_uuids: List[Any]) -> Dict[str, List[str]]:
    """Batch-fetch category item tag ids for a list of finds."""
    if not find_uuids:
        return {}

    rows = await conn.fetch(
        "SELECT find_id, category_item_id "
        "FROM find_tag_items "
        "WHERE find_id = ANY($1::uuid[]) "
        "ORDER BY created_at ASC, category_item_id ASC",
        find_uuids,
    )

    tag_item_ids_by_find_id: Dict[str, List[str]] = {}
    for row in rows:
        fid = str(row["find_id"])
        tag_item_ids_by_find_id.setdefault(fid, []).append(str(row["category_item_id"]))

    return tag_item_ids_by_find_id


async def _replace_find_tag_items(conn: Any, find_id: Any, tag_item_ids: List[str]) -> None:
    """Replace item-tag rows for one find."""
    await conn.execute("DELETE FROM find_tag_items WHERE find_id = $1::uuid", find_id)

    if not tag_item_ids:
        return

    await conn.executemany(
        """
        INSERT INTO find_tag_items (find_id, category_item_id)
        VALUES ($1::uuid, $2::uuid)
        ON CONFLICT (find_id, category_item_id) DO NOTHING
        """,
        [(find_id, tag_item_id) for tag_item_id in tag_item_ids],
    )


async def _fetch_find_category_slugs(conn: Any, find_uuids: List[Any]) -> Dict[str, List[str]]:
    """Batch-fetch top-level category slugs for a list of finds."""
    if not find_uuids:
        return {}

    rows = await conn.fetch(
        "SELECT fc.find_id, c.slug "
        "FROM find_categories fc "
        "JOIN categories c ON c.id = fc.category_id "
        "WHERE fc.find_id = ANY($1::uuid[]) "
        "ORDER BY c.sort_order ASC, c.slug ASC",
        find_uuids,
    )

    category_slugs_by_find_id: Dict[str, List[str]] = {}
    for row in rows:
        fid = str(row["find_id"])
        category_slugs_by_find_id.setdefault(fid, []).append(row["slug"])

    return category_slugs_by_find_id


async def _replace_find_categories(conn: Any, find_id: Any, category_ids: List[str]) -> None:
    """Replace category membership rows for one find."""
    await conn.execute("DELETE FROM find_categories WHERE find_id = $1::uuid", find_id)

    if not category_ids:
        return

    await conn.executemany(
        """
        INSERT INTO find_categories (find_id, category_id)
        VALUES ($1::uuid, $2::uuid)
        ON CONFLICT (find_id, category_id) DO NOTHING
        """,
        [(find_id, category_id) for category_id in category_ids],
    )


async def resolve_category_ids(
    app_variant_id: str,
    category_slugs: List[str],
) -> List[str]:
    """Resolve active top-level category slugs for an app variant."""
    if not category_slugs:
        return []

    conn = await get_db_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT id, slug
            FROM categories
            WHERE app_variant_id = $1::uuid
              AND parent_category_id IS NULL
              AND is_active = TRUE
              AND slug = ANY($2::text[])
            """,
            app_variant_id,
            category_slugs,
        )
        ids_by_slug = {row["slug"]: str(row["id"]) for row in rows}
        return [ids_by_slug[slug] for slug in category_slugs if slug in ids_by_slug]
    finally:
        await release_db_connection(conn)


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
    periods: Optional[List[str]],
    top_category_slug: Optional[str],
    item_id: Optional[str],
    tag_item_ids: Optional[List[str]] = None,
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
            idx = len(params) + 1
            query += (
                f" AND EXISTS (SELECT 1 FROM find_categories fc "
                f"JOIN categories c ON c.id = fc.category_id "
                f"WHERE fc.find_id = finds.id AND c.slug = ${idx})"
            )
            params.append(segments[0])

    effective_periods = list(dict.fromkeys(
        ([period] if period else []) + list(periods or [])
    ))
    if effective_periods:
        query += f" AND period = ANY(${len(params) + 1}::varchar[])"
        params.append(effective_periods)

    if top_category_slug:
        idx = len(params) + 1
        query += (
            f" AND EXISTS (SELECT 1 FROM find_categories fc "
            f"JOIN categories c ON c.id = fc.category_id "
            f"WHERE fc.find_id = finds.id AND c.slug = ${idx})"
        )
        params.append(top_category_slug)

    if item_id:
        query += (
            f" AND (find_item_id = ${len(params) + 1}::uuid "
            f"OR EXISTS (SELECT 1 FROM find_tag_items fti "
            f"WHERE fti.find_id = finds.id AND fti.category_item_id = ${len(params) + 1}::uuid))"
        )
        params.append(item_id)

    if tag_item_ids:
        query += (
            f" AND (find_item_id = ANY(${len(params) + 1}::uuid[]) "
            f"OR EXISTS (SELECT 1 FROM find_tag_items fti "
            f"WHERE fti.find_id = finds.id AND fti.category_item_id = ANY(${len(params) + 1}::uuid[])))"
        )
        params.append(tag_item_ids)

    return query, params


def _build_find_record(
    row: Any,
    fid: str,
    nicknames_by_user_id: Dict[str, str],
    images_by_id: Dict[str, list],
    comments_by_id: Dict[str, list],
    tag_item_ids_by_find_id: Dict[str, List[str]],
    category_slugs_by_find_id: Dict[str, List[str]],
    include_location: bool,
) -> Dict[str, Any]:
    """Build API record payload from a DB row."""
    category_slugs = category_slugs_by_find_id.get(fid, [])
    payload: Dict[str, Any] = {
        "id": fid,
        "userId": str(row["user_id"]),
        "displayNickname": nicknames_by_user_id.get(str(row["user_id"])),
        "date": row["date"],
        "title": row.get("title") if hasattr(row, "get") else row["title"],
        "description": row["description"],
        "clusterHash": row["cluster_hash"],
        "categoryPaths": [[slug] for slug in category_slugs],
        "period": row["period"],
        "topCategorySlug": category_slugs[0] if len(category_slugs) == 1 else None,
        "itemId": str(row["find_item_id"]) if row.get("find_item_id") is not None else None,
        "tagItemIds": tag_item_ids_by_find_id.get(fid, []),
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
    periods: Optional[List[str]] = None,
    top_category_slug: Optional[str] = None,
    item_id: Optional[str] = None,
    tag_item_ids: Optional[List[str]] = None,
) -> List[dict]:
    """Query public finds with shared filters."""
    conn = await get_db_connection()
    try:
        query = """
            SELECT 
                id, user_id, date, title, description, cluster_hash,
                period, find_item_id, created_at
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
            periods=periods,
            top_category_slug=top_category_slug,
            item_id=item_id,
            tag_item_ids=tag_item_ids,
        )

        query += " ORDER BY date DESC"

        rows = await conn.fetch(query, *params)

        find_uuids = [row["id"] for row in rows]
        owner_ids = [row["user_id"] for row in rows]
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, find_uuids)
        tag_item_ids_by_find_id = await _fetch_find_tag_item_ids(conn, find_uuids)
        category_slugs_by_find_id = await _fetch_find_category_slugs(conn, find_uuids)
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
                    tag_item_ids_by_find_id=tag_item_ids_by_find_id,
                    category_slugs_by_find_id=category_slugs_by_find_id,
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
    periods: Optional[List[str]] = None,
    top_category_slug: Optional[str] = None,
    item_id: Optional[str] = None,
    tag_item_ids: Optional[List[str]] = None,
) -> List[dict]:
    """Query private finds for a specific user with shared filters."""
    conn = await get_db_connection()
    try:
        query = """
            SELECT 
                id, user_id, date, title, description, cluster_hash,
                latitude, longitude, period,
                find_item_id, created_at
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
            periods=periods,
            top_category_slug=top_category_slug,
            item_id=item_id,
            tag_item_ids=tag_item_ids,
        )

        query += " ORDER BY date DESC"

        rows = await conn.fetch(query, *params)

        find_uuids = [row["id"] for row in rows]
        owner_ids = [row["user_id"] for row in rows]
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, find_uuids)
        tag_item_ids_by_find_id = await _fetch_find_tag_item_ids(conn, find_uuids)
        category_slugs_by_find_id = await _fetch_find_category_slugs(conn, find_uuids)
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
                    tag_item_ids_by_find_id=tag_item_ids_by_find_id,
                    category_slugs_by_find_id=category_slugs_by_find_id,
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
    periods: Optional[List[str]] = None,
    top_category_slug: Optional[str] = None,
    item_id: Optional[str] = None,
    tag_item_ids: Optional[List[str]] = None,
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
        periods=periods,
        top_category_slug=top_category_slug,
        item_id=item_id,
        tag_item_ids=tag_item_ids,
    )


async def insert_find(
    user_id: str,
    app_variant_id: str,
    date: datetime,
    title: Optional[str],
    description: str,
    cluster_hash: str,
    latitude: float,
    longitude: float,
    category_ids: Optional[List[str]] = None,
    period: Optional[str] = None,
    find_item_id: Optional[str] = None,
    tag_item_ids: Optional[List[str]] = None,
) -> dict:
    """Insert a new find record into database and return API payload."""
    derived_period = _period_for_date(date)
    conn = await get_db_connection()
    try:
        query = """
            INSERT INTO finds (
                user_id, app_variant_id, date, title, description, cluster_hash,
                latitude, longitude, period, find_item_id
            )
            VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10::uuid)
            RETURNING id, user_id, date, title, description, cluster_hash,
                      latitude, longitude, period, find_item_id, created_at
        """

        row = await conn.fetchrow(
            query,
            user_id,
            app_variant_id,
            date,
            title,
            description,
            cluster_hash,
            latitude,
            longitude,
            derived_period,
            find_item_id,
        )

        effective_tag_item_ids = tag_item_ids or ([find_item_id] if find_item_id else [])
        if effective_tag_item_ids:
            await _replace_find_tag_items(conn, row["id"], effective_tag_item_ids)
        await _replace_find_categories(conn, row["id"], category_ids or [])

        fid = str(row["id"])
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, [row["id"]])
        tag_item_ids_by_find_id = await _fetch_find_tag_item_ids(conn, [row["id"]])
        category_slugs_by_find_id = await _fetch_find_category_slugs(conn, [row["id"]])
        nicknames_by_user_id = await _fetch_display_nicknames(conn, [row["user_id"]])
        return _build_find_record(
            row=row,
            fid=fid,
            nicknames_by_user_id=nicknames_by_user_id,
            images_by_id=images_by_id,
            comments_by_id=comments_by_id,
            tag_item_ids_by_find_id=tag_item_ids_by_find_id,
            category_slugs_by_find_id=category_slugs_by_find_id,
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
            SELECT id, user_id, date, title, description, cluster_hash,
                     latitude, longitude, period, find_item_id
            FROM finds WHERE id = $1::uuid AND user_id = $2::uuid
            """,
            find_id,
            user_id,
        )
        if row is None:
            return None

        fid = str(row["id"])
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, [row["id"]])
        tag_item_ids_by_find_id = await _fetch_find_tag_item_ids(conn, [row["id"]])
        category_slugs_by_find_id = await _fetch_find_category_slugs(conn, [row["id"]])
        nicknames_by_user_id = await _fetch_display_nicknames(conn, [row["user_id"]])
        return _build_find_record(
            row=row,
            fid=fid,
            nicknames_by_user_id=nicknames_by_user_id,
            images_by_id=images_by_id,
            comments_by_id=comments_by_id,
            tag_item_ids_by_find_id=tag_item_ids_by_find_id,
            category_slugs_by_find_id=category_slugs_by_find_id,
            include_location=True,
        )
    finally:
        await release_db_connection(conn)


async def insert_find_comment(
    find_id: str,
    user_id: str,
    text: str,
) -> Optional[dict]:
    """Insert a comment only when its find is publicly visible."""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO find_comments (
                find_id,
                user_id,
                text,
                language_code,
                app_variant_id
            )
            SELECT $1::uuid, $2::uuid, $3, 'sk', f.app_variant_id
            FROM finds f
            WHERE f.id = $1::uuid AND f.allow_public = TRUE
            RETURNING id, user_id, text, created_at
            """,
            find_id,
            user_id,
            text,
        )
        if row is None:
            return None

        nicknames = await _fetch_display_nicknames(conn, [row["user_id"]])
        return {
            "id": str(row["id"]),
            "userId": str(row["user_id"]),
            "displayNickname": nicknames.get(str(row["user_id"])),
            "text": row["text"],
            "createdAt": row["created_at"],
        }
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
    title: Optional[str] = None,
    description: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    category_ids: Optional[List[str]] = None,
    period: Optional[str] = None,
    find_item_id: Optional[str] = None,
    tag_item_ids: Optional[List[str]] = None,
) -> Optional[dict]:
    """Update mutable fields of a find. Returns None if find does not exist."""
    conn = await get_db_connection()
    try:
        set_parts: List[str] = []
        params: List[Any] = []

        if date is not None:
            params.append(date)
            set_parts.append(f"date = ${len(params)}")
            params.append(_period_for_date(date))
            set_parts.append(f"period = ${len(params)}")
        if title is not None:
            params.append(title)
            set_parts.append(f"title = ${len(params)}")
        if description is not None:
            params.append(description)
            set_parts.append(f"description = ${len(params)}")
        if latitude is not None:
            params.append(latitude)
            set_parts.append(f"latitude = ${len(params)}")
        if longitude is not None:
            params.append(longitude)
            set_parts.append(f"longitude = ${len(params)}")
        if period is not None and date is None:
            params.append(period)
            set_parts.append(f"period = ${len(params)}")
        if find_item_id is not None:
            params.append(find_item_id)
            set_parts.append(f"find_item_id = ${len(params)}::uuid")

        if not set_parts and tag_item_ids is None and category_ids is None:
            return await get_find_by_id(find_id, user_id)

        if set_parts:
            set_parts.append("updated_at = now()")
        params.append(find_id)
        params.append(user_id)

        if set_parts:
            query = f"""
                UPDATE finds SET {', '.join(set_parts)}
                            WHERE id = ${len(params) - 1}::uuid
                                AND user_id = ${len(params)}::uuid
                RETURNING id, user_id, date, title, description, cluster_hash,
                          latitude, longitude, period, find_item_id
            """
            row = await conn.fetchrow(query, *params)
        else:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, date, title, description, cluster_hash,
                       latitude, longitude, period, find_item_id
                FROM finds
                WHERE id = $1::uuid AND user_id = $2::uuid
                """,
                find_id,
                user_id,
            )
        if row is None:
            return None

        if tag_item_ids is not None:
            await _replace_find_tag_items(conn, row["id"], tag_item_ids)
        if category_ids is not None:
            await _replace_find_categories(conn, row["id"], category_ids)

        fid = str(row["id"])
        images_by_id, comments_by_id = await _fetch_images_and_comments(conn, [row["id"]])
        tag_item_ids_by_find_id = await _fetch_find_tag_item_ids(conn, [row["id"]])
        category_slugs_by_find_id = await _fetch_find_category_slugs(conn, [row["id"]])
        nicknames_by_user_id = await _fetch_display_nicknames(conn, [row["user_id"]])
        return _build_find_record(
            row=row,
            fid=fid,
            nicknames_by_user_id=nicknames_by_user_id,
            images_by_id=images_by_id,
            comments_by_id=comments_by_id,
            tag_item_ids_by_find_id=tag_item_ids_by_find_id,
            category_slugs_by_find_id=category_slugs_by_find_id,
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


async def get_user_active_variant(user_id: str) -> Optional[dict]:
    """Resolve active/default app variant for a user."""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT v.id, v.code, v.display_name, v.default_language_code,
                   v.default_map_center_lat, v.default_map_center_lng,
                   v.default_map_zoom, v.topmenu_icon_set, v.theme_tokens
            FROM user_variant_memberships m
            JOIN app_variants v ON v.id = m.app_variant_id
            WHERE m.user_id = $1::uuid
              AND m.is_active = TRUE
              AND v.is_active = TRUE
            ORDER BY m.is_default DESC, m.created_at ASC
            LIMIT 1
            """,
            user_id,
        )
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "code": row["code"],
            "displayName": row["display_name"],
            "defaultLanguageCode": row["default_language_code"],
            "defaultMapCenterLat": row["default_map_center_lat"],
            "defaultMapCenterLng": row["default_map_center_lng"],
            "defaultMapZoom": float(row["default_map_zoom"]),
            "topmenuIconSet": row["topmenu_icon_set"],
            "themeTokens": row["theme_tokens"],
        }
    finally:
        await release_db_connection(conn)


async def list_top_categories(app_variant_id: str, language_code: str) -> List[dict]:
    """List top-level categories with localized labels for one variant."""
    conn = await get_db_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT c.id, c.slug, c.icon_key, c.sort_order,
                   COALESCE(ct.label, c.slug) AS label
            FROM categories c
            LEFT JOIN category_translations ct
              ON ct.category_id = c.id
             AND ct.language_code = $2
            WHERE c.app_variant_id = $1::uuid
              AND c.parent_category_id IS NULL
              AND c.is_active = TRUE
            ORDER BY c.sort_order ASC, c.slug ASC
            """,
            app_variant_id,
            language_code,
        )
        return [
            {
                "id": str(r["id"]),
                "slug": r["slug"],
                "iconKey": r["icon_key"],
                "label": r["label"],
                "sortOrder": r["sort_order"],
            }
            for r in rows
        ]
    finally:
        await release_db_connection(conn)


async def list_category_items(
    user_id: str,
    app_variant_id: str,
    language_code: str,
    top_category_slug: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[dict]:
    """List category items in one feed (admin + approved + own items)."""
    conn = await get_db_connection()
    try:
        sql = """
            SELECT ci.id,
                   ci.category_id,
                   ci.canonical_key,
                   ci.owner_type,
                   ci.visibility_state,
                   ci.approval_state,
                   ci.promoted_to_admin,
                   ci.image_url,
                   ci.created_by_user_id,
                   c.slug AS category_slug,
                   COALESCE(p.slug, c.slug) AS top_category_slug,
                   COALESCE(ct_top.label, COALESCE(p.slug, c.slug)) AS top_category_label,
                   COALESCE(cit.title, ci.canonical_key, c.slug) AS title,
                   cit.description_text
            FROM category_items ci
            JOIN categories c ON c.id = ci.category_id
            LEFT JOIN categories p ON p.id = c.parent_category_id
            LEFT JOIN category_item_translations cit
              ON cit.item_id = ci.id
             AND cit.language_code = $3
            LEFT JOIN category_translations ct_top
              ON ct_top.category_id = COALESCE(p.id, c.id)
             AND ct_top.language_code = $3
            WHERE ci.app_variant_id = $1::uuid
              AND ci.visibility_state = 'visible'
              AND (
                    ci.owner_type = 'admin'
                 OR ci.approval_state = 'approved'
                 OR ci.created_by_user_id = $2::uuid
              )
        """
        params: List[Any] = [app_variant_id, user_id, language_code]

        if top_category_slug:
            sql += f" AND COALESCE(p.slug, c.slug) = ${len(params) + 1}"
            params.append(top_category_slug)

        if q:
            sql += f" AND (cit.search_tsv @@ websearch_to_tsquery('simple', ${len(params) + 1}) OR LOWER(COALESCE(cit.title, '')) LIKE LOWER(${len(params) + 2}))"
            params.append(q)
            params.append(f"%{q}%")

        sql += f" ORDER BY COALESCE(p.slug, c.slug), cit.title NULLS LAST, ci.created_at DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
        params.append(limit)
        params.append(offset)

        rows = await conn.fetch(sql, *params)
        return [
            {
                "id": str(r["id"]),
                "categoryId": str(r["category_id"]),
                "categorySlug": r["category_slug"],
                "topCategorySlug": r["top_category_slug"],
                "topCategoryLabel": r["top_category_label"],
                "canonicalKey": r["canonical_key"],
                "title": r["title"],
                "descriptionText": r["description_text"],
                "imageUrl": r["image_url"],
                "ownerType": r["owner_type"],
                "approvalState": r["approval_state"],
                "promotedToAdmin": r["promoted_to_admin"],
                "createdByUserId": str(r["created_by_user_id"]),
            }
            for r in rows
        ]
    finally:
        await release_db_connection(conn)


def _canonicalize_item_title(title: str) -> str:
    """Normalize item title to a stable canonical key for deduplication."""
    normalized = re.sub(r"\s+", " ", title.strip().lower())
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized


async def create_category_item(
    user_id: str,
    app_variant_id: str,
    language_code: str,
    top_category_slug: str,
    category_slug: str,
    title: str,
    description_text: Optional[str] = None,
) -> dict:
    """Create a user-owned category item or return an already-visible canonical match."""
    normalized_title = title.strip()
    if len(normalized_title) < 2:
        raise ValueError("category_item_error_title_too_short")

    canonical_key = _canonicalize_item_title(normalized_title)
    if not canonical_key:
        raise ValueError("category_item_error_title_invalid")

    normalized_description = description_text.strip() if isinstance(description_text, str) else None

    conn = await get_db_connection()
    try:
        existing = await conn.fetchrow(
            """
            WITH target_category AS (
                SELECT c.id AS category_id
                FROM categories c
                LEFT JOIN categories p ON p.id = c.parent_category_id
                WHERE c.app_variant_id = $1::uuid
                  AND c.slug = $2
                  AND COALESCE(p.slug, c.slug) = $3
                LIMIT 1
            )
            SELECT ci.id,
                   ci.category_id,
                   c.slug AS category_slug,
                   COALESCE(p.slug, c.slug) AS top_category_slug,
                   COALESCE(ct_top.label, COALESCE(p.slug, c.slug)) AS top_category_label,
                   ci.canonical_key,
                   COALESCE(cit.title, ci.canonical_key, c.slug) AS title,
                   cit.description_text,
                   ci.image_url,
                   ci.owner_type,
                   ci.approval_state,
                   ci.promoted_to_admin,
                   ci.created_by_user_id
            FROM category_items ci
            JOIN target_category tc ON tc.category_id = ci.category_id
            JOIN categories c ON c.id = ci.category_id
            LEFT JOIN categories p ON p.id = c.parent_category_id
            LEFT JOIN category_item_translations cit
              ON cit.item_id = ci.id
             AND cit.language_code = $6
            LEFT JOIN category_translations ct_top
              ON ct_top.category_id = COALESCE(p.id, c.id)
             AND ct_top.language_code = $6
            WHERE ci.canonical_key = $4
              AND ci.visibility_state = 'visible'
              AND (
                    ci.owner_type = 'admin'
                 OR ci.approval_state = 'approved'
                 OR ci.created_by_user_id = $5::uuid
              )
            LIMIT 1
            """,
            app_variant_id,
            category_slug,
            top_category_slug,
            canonical_key,
            user_id,
            language_code,
        )
        if existing is not None:
            return {
                "id": str(existing["id"]),
                "categoryId": str(existing["category_id"]),
                "categorySlug": existing["category_slug"],
                "topCategorySlug": existing["top_category_slug"],
                "topCategoryLabel": existing["top_category_label"],
                "canonicalKey": existing["canonical_key"],
                "title": existing["title"],
                "descriptionText": existing["description_text"],
                "imageUrl": existing["image_url"],
                "ownerType": existing["owner_type"],
                "approvalState": existing["approval_state"],
                "promotedToAdmin": existing["promoted_to_admin"],
                "createdByUserId": str(existing["created_by_user_id"]),
            }

        inserted = await conn.fetchrow(
            """
            WITH target_category AS (
                SELECT c.id AS category_id
                FROM categories c
                LEFT JOIN categories p ON p.id = c.parent_category_id
                WHERE c.app_variant_id = $1::uuid
                  AND c.slug = $2
                  AND COALESCE(p.slug, c.slug) = $3
                LIMIT 1
            )
            INSERT INTO category_items (
                app_variant_id,
                category_id,
                canonical_key,
                created_by_user_id,
                owner_type,
                visibility_state,
                approval_state
            )
            SELECT
                $1::uuid,
                tc.category_id,
                $4,
                $5::uuid,
                'user',
                'visible',
                'none'
            FROM target_category tc
            RETURNING id, category_id
            """,
            app_variant_id,
            category_slug,
            top_category_slug,
            canonical_key,
            user_id,
        )

        if inserted is None:
            raise ValueError("category_item_error_invalid_category")

        await conn.execute(
            """
            INSERT INTO category_item_translations (item_id, language_code, title, description_text)
            VALUES ($1::uuid, $2, $3, $4)
            ON CONFLICT (item_id, language_code)
            DO UPDATE SET
                title = EXCLUDED.title,
                description_text = EXCLUDED.description_text
            """,
            inserted["id"],
            language_code,
            normalized_title,
            normalized_description,
        )

        row = await conn.fetchrow(
            """
            SELECT ci.id,
                   ci.category_id,
                   c.slug AS category_slug,
                   COALESCE(p.slug, c.slug) AS top_category_slug,
                   COALESCE(ct_top.label, COALESCE(p.slug, c.slug)) AS top_category_label,
                   ci.canonical_key,
                   COALESCE(cit.title, ci.canonical_key, c.slug) AS title,
                   cit.description_text,
                   ci.image_url,
                   ci.owner_type,
                   ci.approval_state,
                   ci.promoted_to_admin,
                   ci.created_by_user_id
            FROM category_items ci
            JOIN categories c ON c.id = ci.category_id
            LEFT JOIN categories p ON p.id = c.parent_category_id
            LEFT JOIN category_item_translations cit
              ON cit.item_id = ci.id
             AND cit.language_code = $2
            LEFT JOIN category_translations ct_top
              ON ct_top.category_id = COALESCE(p.id, c.id)
             AND ct_top.language_code = $2
            WHERE ci.id = $1::uuid
            LIMIT 1
            """,
            inserted["id"],
            language_code,
        )

        if row is None:
            raise ValueError("category_item_error_invalid_category")

        return {
            "id": str(row["id"]),
            "categoryId": str(row["category_id"]),
            "categorySlug": row["category_slug"],
            "topCategorySlug": row["top_category_slug"],
            "topCategoryLabel": row["top_category_label"],
            "canonicalKey": row["canonical_key"],
            "title": row["title"],
            "descriptionText": row["description_text"],
            "imageUrl": row["image_url"],
            "ownerType": row["owner_type"],
            "approvalState": row["approval_state"],
            "promotedToAdmin": row["promoted_to_admin"],
            "createdByUserId": str(row["created_by_user_id"]),
        }
    except ValueError:
        raise
    except Exception as e:
        if "ux_category_items_category_canonical_key" in str(e):
            raise ValueError("category_item_error_duplicate_inaccessible")
        raise
    finally:
        await release_db_connection(conn)


async def resolve_item_context(
    user_id: str,
    app_variant_id: str,
    item_id: str,
    language_code: str,
) -> Optional[dict]:
    """Validate item visibility and return top/category context for find creation."""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT ci.id,
                   ci.canonical_key,
                   c.slug AS category_slug,
                   COALESCE(p.slug, c.slug) AS top_category_slug,
                   COALESCE(p.id, c.id) AS category_id,
                   COALESCE(cit.title, ci.canonical_key, c.slug) AS item_title
            FROM category_items ci
            JOIN categories c ON c.id = ci.category_id
            LEFT JOIN categories p ON p.id = c.parent_category_id
            LEFT JOIN category_item_translations cit
              ON cit.item_id = ci.id
             AND cit.language_code = $4
            WHERE ci.id = $3::uuid
              AND ci.app_variant_id = $2::uuid
              AND ci.visibility_state = 'visible'
              AND (
                    ci.owner_type = 'admin'
                 OR ci.approval_state = 'approved'
                 OR ci.created_by_user_id = $1::uuid
              )
            LIMIT 1
            """,
            user_id,
            app_variant_id,
            item_id,
            language_code,
        )
        if row is None:
            return None

        item_key = row["canonical_key"] or str(row["id"])
        return {
            "itemId": str(row["id"]),
            "topCategorySlug": row["top_category_slug"],
            "categorySlug": row["category_slug"],
            "categoryId": str(row["category_id"]),
            "itemTitle": row["item_title"],
            "categoryPath": [[row["top_category_slug"], row["category_slug"], item_key]],
        }
    finally:
        await release_db_connection(conn)
