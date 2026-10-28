from datetime import datetime
from unittest.mock import AsyncMock

import pytest

import queries
from queries import (
    _apply_find_filters,
    _build_find_record,
    _fetch_like_data,
    _period_for_date,
    insert_find,
    insert_find_comment,
    set_find_like,
)


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
    assert params == ["porcini forest", "porcini forest"]


def test_search_ignores_diacritics_in_params_and_sql():
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
        search_query="Jaseň",
    )

    assert params == ["Jaseň", "jasen"]
    assert "translate(LOWER(" in query
    assert queries.strip_diacritics("Čučoriedka ŽLTÝ ľ") == "cucoriedka zlty l"


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
        item_titles_by_id={"00000000-0000-0000-0000-000000000123": "Hríb smrekový"},
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
        item_titles_by_id={"00000000-0000-0000-0000-000000000123": "Hríb smrekový"},
        include_location=False,
    )

    assert "location" in with_location
    assert with_location["location"]["latitude"] == 48.14
    assert with_location["title"] == "Test title"
    assert with_location["categoryPaths"] == [["mushrooms"]]
    assert with_location["topCategorySlug"] == "mushrooms"
    assert with_location["tagItemIds"] == ["00000000-0000-0000-0000-000000000123"]
    assert with_location["itemLabel"] == "Hríb smrekový"
    assert with_location["itemLabels"] == ["Hríb smrekový"]
    assert "location" not in without_location


def test_build_find_record_includes_engagement_counts():
    row = {
        "id": "a",
        "user_id": "u1",
        "date": datetime(2026, 1, 1),
        "title": None,
        "description": "desc",
        "cluster_hash": "48.14_17.11",
        "period": "JAN_1",
        "find_item_id": None,
    }
    payload = _build_find_record(
        row=row,
        fid="a",
        nicknames_by_user_id={},
        images_by_id={"a": []},
        comments_by_id={
            "a": [
                {"isMisidentificationReport": True},
                {"isMisidentificationReport": False},
            ]
        },
        tag_item_ids_by_find_id={},
        category_slugs_by_find_id={},
        item_titles_by_id={},
        include_location=False,
        like_data_by_find_id={
            "a": {"likeCount": 4, "likedByMe": True},
        },
    )

    assert payload["likeCount"] == 4
    assert payload["likedByMe"] is True
    assert payload["misidentificationCount"] == 1


@pytest.mark.asyncio
async def test_fetch_like_data_maps_counts_and_current_user_state():
    conn = AsyncMock()
    conn.fetch.return_value = [
        {"find_id": "find-1", "like_count": 3, "liked_by_me": True},
    ]

    result = await _fetch_like_data(conn, ["find-1"], "user-1")

    assert result == {
        "find-1": {"likeCount": 3, "likedByMe": True},
    }
    conn.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_find_like_is_idempotent_and_returns_updated_count(monkeypatch):
    conn = AsyncMock()
    conn.fetchrow.return_value = {"user_id": "owner-1"}
    conn.fetchval.return_value = 2
    released = AsyncMock()
    monkeypatch.setattr(queries, "get_db_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(queries, "release_db_connection", released)

    result = await set_find_like("find-1", "user-1", True)

    assert result == {"likeCount": 2, "likedByMe": True}
    assert "ON CONFLICT (find_id, user_id) DO NOTHING" in conn.execute.await_args.args[0]
    released.assert_awaited_once_with(conn)


@pytest.mark.asyncio
async def test_insert_find_comment_persists_report_flag(monkeypatch):
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "id": "comment-1",
        "user_id": "user-1",
        "text": "Wrong species",
        "created_at": datetime(2026, 10, 1),
        "is_misidentification_report": True,
    }
    conn.fetchval.return_value = False
    monkeypatch.setattr(queries, "get_db_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(queries, "release_db_connection", AsyncMock())
    monkeypatch.setattr(
        queries,
        "_fetch_display_nicknames",
        AsyncMock(return_value={"user-1": "tester"}),
    )

    comment = await insert_find_comment(
        "find-1",
        "user-1",
        "Wrong species",
        is_misidentification_report=True,
    )

    assert comment["isMisidentificationReport"] is True
    assert "is_misidentification_report" in conn.fetchrow.await_args.args[0]


@pytest.mark.asyncio
async def test_insert_find_comment_rejects_second_report(monkeypatch):
    conn = AsyncMock()
    conn.fetchval.side_effect = [False, True]
    monkeypatch.setattr(queries, "get_db_connection", AsyncMock(return_value=conn))
    released = AsyncMock()
    monkeypatch.setattr(queries, "release_db_connection", released)

    with pytest.raises(ValueError, match="misidentification_already_reported"):
        await insert_find_comment(
            "find-1",
            "user-1",
            "Still wrong",
            is_misidentification_report=True,
        )

    conn.fetchrow.assert_not_awaited()
    released.assert_awaited_once_with(conn)


@pytest.mark.asyncio
async def test_insert_find_returns_item_labels(monkeypatch):
    find_id = "find-1"
    item_id = "00000000-0000-0000-0000-000000000123"
    user_id = "00000000-0000-0000-0000-000000000456"
    row = {
        "id": find_id,
        "user_id": user_id,
        "date": datetime(2026, 9, 28),
        "title": "First animal",
        "description": "A wildlife find",
        "cluster_hash": "181_70",
        "latitude": 49.13,
        "longitude": 19.06,
        "period": "SEP_2",
        "find_item_id": item_id,
    }
    conn = AsyncMock()
    conn.fetchrow.return_value = row
    released = AsyncMock()

    monkeypatch.setattr(queries, "get_db_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(queries, "release_db_connection", released)
    monkeypatch.setattr(queries, "_replace_find_tag_items", AsyncMock())
    monkeypatch.setattr(queries, "_replace_find_categories", AsyncMock())
    monkeypatch.setattr(
        queries,
        "_fetch_images_and_comments",
        AsyncMock(return_value=({}, {})),
    )
    monkeypatch.setattr(
        queries,
        "_fetch_find_tag_item_ids",
        AsyncMock(return_value={find_id: [item_id]}),
    )
    monkeypatch.setattr(
        queries,
        "_fetch_find_category_slugs",
        AsyncMock(return_value={find_id: ["wildlife"]}),
    )
    monkeypatch.setattr(
        queries,
        "_fetch_display_nicknames",
        AsyncMock(return_value={user_id: "tester"}),
    )
    monkeypatch.setattr(
        queries,
        "_fetch_item_titles",
        AsyncMock(return_value={item_id: "Unknown"}),
    )

    result = await insert_find(
        user_id=user_id,
        app_variant_id="00000000-0000-0000-0000-000000000789",
        date=datetime(2026, 9, 28),
        title="First animal",
        description="A wildlife find",
        cluster_hash="181_70",
        latitude=49.13,
        longitude=19.06,
        category_ids=["00000000-0000-0000-0000-000000000321"],
        find_item_id=item_id,
        tag_item_ids=[item_id],
    )

    assert result["itemLabel"] == "Unknown"
    assert result["itemLabels"] == ["Unknown"]
    released.assert_awaited_once_with(conn)


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
    assert "SELECT $1::uuid, $2::uuid, $3, 'sk', f.app_variant_id, $4" in query
    assert params == [
        "00000000-0000-0000-0000-000000000888",
        "00000000-0000-0000-0000-000000000777",
        "Test comment",
        False,
    ]
    assert comment["displayNickname"] == "tester"
    assert comment["isMisidentificationReport"] is False
    released.assert_awaited_once_with(conn)


class _FakeUniqueViolation(Exception):
    def __init__(self, constraint):
        super().__init__("duplicate")
        self.sqlstate = "23505"
        self.constraint_name = constraint


def test_unique_violation_maps_to_group_error_codes():
    seq = queries._unique_violation_error(_FakeUniqueViolation("ux_finds_group_seq"))
    pk = queries._unique_violation_error(_FakeUniqueViolation("finds_pkey"))

    assert seq.code == "group_seq_conflict"
    assert pk.code == "find_id_conflict"
    assert queries._unique_violation_error(ValueError("x")) is None


@pytest.mark.asyncio
async def test_dissolve_find_group_returns_false_for_non_owner_or_solo(monkeypatch):
    conn = AsyncMock()
    conn.fetchval.return_value = None
    monkeypatch.setattr(queries, "get_db_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(queries, "release_db_connection", AsyncMock())

    assert await queries.dissolve_find_group("f", "u") is False
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_find_group_members_hides_unavailable_and_coordinates(monkeypatch):
    from unittest.mock import MagicMock

    owner = "00000000-0000-0000-0000-000000000001"
    group_id = "00000000-0000-0000-0000-0000000000aa"
    rows = [
        {
            "id": f"00000000-0000-0000-0000-00000000010{i}",
            "user_id": owner,
            "date": datetime(2026, 9, 28),
            "title": "Hríby",
            "description": f"n{i}",
            "cluster_hash": "181_70",
            "latitude": 49.1,
            "longitude": 19.0,
            "period": "SEP_2",
            "find_item_id": None,
            "group_id": group_id,
            "group_seq": i,
            "captured_at": None,
        }
        for i in (1, 2)
    ]
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "id": rows[0]["id"],
        "user_id": owner,
        "group_id": group_id,
        "allow_public": True,
    }
    conn.fetch.return_value = rows
    monkeypatch.setattr(queries, "get_db_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(queries, "release_db_connection", AsyncMock())
    monkeypatch.setattr(queries, "_fetch_group_counts", AsyncMock(return_value={group_id: 2}))
    monkeypatch.setattr(queries, "_fetch_images_and_comments", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr(queries, "_fetch_like_data", AsyncMock(return_value={}))
    monkeypatch.setattr(queries, "_fetch_find_tag_item_ids", AsyncMock(return_value={}))
    monkeypatch.setattr(queries, "_fetch_find_category_slugs", AsyncMock(return_value={}))
    monkeypatch.setattr(queries, "_fetch_display_nicknames", AsyncMock(return_value={}))
    monkeypatch.setattr(queries, "_fetch_item_titles", AsyncMock(return_value={}))

    as_owner = await queries.get_find_group_members(rows[0]["id"], owner)
    as_other = await queries.get_find_group_members(rows[0]["id"], None)

    assert [m["groupSeq"] for m in as_owner] == [1, 2]
    assert all(m["groupCount"] == 2 for m in as_owner)
    assert all("location" in m for m in as_owner)
    assert all("location" not in m for m in as_other)

    conn.fetchrow.return_value = {
        "id": rows[0]["id"],
        "user_id": owner,
        "group_id": group_id,
        "allow_public": False,
    }
    assert await queries.get_find_group_members(rows[0]["id"], None) is None
