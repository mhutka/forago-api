from datetime import datetime
from unittest.mock import AsyncMock

import pytest

import queries
from queries import _apply_find_filters, _build_find_record


def test_apply_find_filters_builds_expected_sql_and_params():
    base_query = "SELECT * FROM finds WHERE allow_public = TRUE"
    params = []

    query, out_params = _apply_find_filters(
        query=base_query,
        params=params,
        cluster="48.14_17.11",
        category="nature/forest",
        from_date=datetime(2026, 1, 1),
        to_date=datetime(2026, 2, 1),
        period="JAN_2",
    )

    assert "cluster_hash = $1" in query
    assert "date >= $2" in query
    assert "date <= $3" in query
    assert "category_paths @> $4::jsonb[]" in query
    assert "period = $5" in query
    assert out_params[0] == "48.14_17.11"
    assert out_params[4] == "JAN_2"


def test_build_find_record_includes_location_only_when_requested():
    row = {
        "id": "a",
        "user_id": "u1",
        "date": datetime(2026, 1, 1),
        "description": "desc",
        "cluster_hash": "48.14_17.11",
        "category_paths": [["nature", "forest"]],
        "period": "JAN_1",
        "latitude": 48.14,
        "longitude": 17.11,
    }

    with_location = _build_find_record(
        row=row,
        fid="a",
        nicknames_by_user_id={"u1": "nick"},
        images_by_id={"a": [{"thumbnailUrl": "t", "fullUrl": "f", "storageRef": None}]},
        comments_by_id={"a": []},
        include_location=True,
    )
    without_location = _build_find_record(
        row=row,
        fid="a",
        nicknames_by_user_id={"u1": "nick"},
        images_by_id={"a": []},
        comments_by_id={"a": []},
        include_location=False,
    )

    assert "location" in with_location
    assert with_location["location"]["latitude"] == 48.14
    assert "location" not in without_location


@pytest.mark.asyncio
async def test_ensure_user_profile_releases_connection(monkeypatch):
    conn = AsyncMock()
    released = AsyncMock()
    expected_profile = {
        "userId": "00000000-0000-0000-0000-000000000777",
        "displayNickname": "tester",
    }

    monkeypatch.setattr(queries, "get_db_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(queries, "release_db_connection", released)
    monkeypatch.setattr(queries, "get_user_profile", AsyncMock(return_value=expected_profile))

    profile = await queries.ensure_user_profile(
        user_id="00000000-0000-0000-0000-000000000777",
        fallback_nickname="tester",
        fallback_display_name="Tester",
    )

    assert profile == expected_profile
    conn.execute.assert_awaited_once()
    released.assert_awaited_once_with(conn)
    conn.close.assert_not_awaited()
