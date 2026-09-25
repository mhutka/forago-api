from datetime import datetime
from unittest.mock import AsyncMock

import pytest

import queries
from queries import _apply_find_filters, _build_find_record, _period_for_date


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 1, 15), "JAN_1"),
        (datetime(2026, 1, 16), "JAN_2"),
        (datetime(2026, 12, 31), "DEC_2"),
    ],
)
def test_period_for_date_uses_half_month_boundaries(value, expected):
    assert _period_for_date(value) == expected


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
        periods=["JAN_2", "FEB_1"],
        top_category_slug="mushrooms",
        item_id="00000000-0000-0000-0000-000000000123",
        tag_item_ids=["00000000-0000-0000-0000-000000000124"],
    )

    assert "cluster_hash = $1" in query
    assert "date >= $2" in query
    assert "date <= $3" in query
    assert "find_categories fc" in query
    assert "c.slug = $4" in query
    assert "period = ANY($5::varchar[])" in query
    assert "c.slug = $6" in query
    assert "find_item_id = $7::uuid" in query
    assert "find_item_id = ANY($8::uuid[])" in query
    assert out_params[0] == "48.14_17.11"
    assert out_params[4] == ["JAN_2", "FEB_1"]
    assert out_params[5] == "mushrooms"
    assert out_params[6] == "00000000-0000-0000-0000-000000000123"
    assert out_params[7] == ["00000000-0000-0000-0000-000000000124"]


def test_apply_find_filters_adds_fulltext_search_across_find_metadata():
    query, params = _apply_find_filters(
        query="SELECT * FROM finds WHERE allow_public = TRUE",
        params=[],
        cluster=None,
        category=None,
        from_date=None,
        to_date=None,
        period=None,
        periods=None,
        top_category_slug=None,
        item_id=None,
        tag_item_ids=None,
        search_query="porcini forest",
    )

    assert "websearch_to_tsquery('simple', $1)" in query
    assert "category_item_translations" in query
    assert "category_translations" in query
    assert "LOWER(COALESCE(finds.title" in query
    assert "profiles p" in query
    assert params == ["porcini forest"]


def test_build_find_record_includes_location_only_when_requested():
    row = {
        "id": "a",
        "user_id": "u1",
        "date": datetime(2026, 1, 1),
        "title": "Test title",
        "description": "desc",
        "cluster_hash": "48.14_17.11",
        "period": "JAN_1",
        "latitude": 48.14,
        "longitude": 17.11,
        "find_item_id": "00000000-0000-0000-0000-000000000123",
    }

    with_location = _build_find_record(
        row=row,
        fid="a",
        nicknames_by_user_id={"u1": "nick"},
        images_by_id={"a": [{"thumbnailUrl": "t", "fullUrl": "f", "storageRef": None}]},
        comments_by_id={"a": []},
        tag_item_ids_by_find_id={"a": ["00000000-0000-0000-0000-000000000123"]},
        category_slugs_by_find_id={"a": ["mushrooms"]},
        include_location=True,
    )
    without_location = _build_find_record(
        row=row,
        fid="a",
        nicknames_by_user_id={"u1": "nick"},
        images_by_id={"a": []},
        comments_by_id={"a": []},
        tag_item_ids_by_find_id={"a": ["00000000-0000-0000-0000-000000000123"]},
        category_slugs_by_find_id={"a": ["mushrooms"]},
        include_location=False,
    )

    assert "location" in with_location
    assert with_location["location"]["latitude"] == 48.14
    assert with_location["title"] == "Test title"
    assert with_location["categoryPaths"] == [["mushrooms"]]
    assert with_location["topCategorySlug"] == "mushrooms"
    assert with_location["tagItemIds"] == ["00000000-0000-0000-0000-000000000123"]
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


@pytest.mark.asyncio
async def test_insert_find_comment_populates_required_metadata(monkeypatch):
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "id": "comment-1",
        "user_id": "00000000-0000-0000-0000-000000000777",
        "text": "Test comment",
        "created_at": datetime(2026, 9, 12),
    }
    released = AsyncMock()

    monkeypatch.setattr(queries, "get_db_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(queries, "release_db_connection", released)
    monkeypatch.setattr(
        queries,
        "_fetch_display_nicknames",
        AsyncMock(return_value={"00000000-0000-0000-0000-000000000777": "tester"}),
    )

    comment = await queries.insert_find_comment(
        find_id="00000000-0000-0000-0000-000000000888",
        user_id="00000000-0000-0000-0000-000000000777",
        text="Test comment",
    )

    query, *params = conn.fetchrow.await_args.args
    assert "language_code" in query
    assert "app_variant_id" in query
    assert "SELECT $1::uuid, $2::uuid, $3, 'sk', f.app_variant_id" in query
    assert params == [
        "00000000-0000-0000-0000-000000000888",
        "00000000-0000-0000-0000-000000000777",
        "Test comment",
    ]
    assert comment["displayNickname"] == "tester"
    released.assert_awaited_once_with(conn)
