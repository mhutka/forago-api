from unittest.mock import MagicMock, call

import pytest

import r2_storage


def test_delete_find_image_objects_removes_both_owned_variants(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(r2_storage, "get_r2_client", lambda: client)
    monkeypatch.setattr(r2_storage, "R2_BUCKET", "forago-images")

    r2_storage.delete_find_image_objects(
        user_id="user-1",
        find_id="find-1",
        storage_ref="finds/user-1/find-1/photo_1",
    )

    assert client.delete_object.call_args_list == [
        call(Bucket="forago-images", Key="finds/user-1/find-1/photo_1_thumb.jpg"),
        call(Bucket="forago-images", Key="finds/user-1/find-1/photo_1_full.jpg"),
    ]


@pytest.mark.parametrize(
    "storage_ref",
    [
        "finds/another-user/find-1/photo",
        "finds/user-1/another-find/photo",
        "finds/user-1/find-1/../other",
        "finds/user-1/find-1/photo/child",
    ],
)
def test_delete_find_image_objects_rejects_out_of_scope_keys(storage_ref):
    with pytest.raises(ValueError, match="Invalid storage reference"):
        r2_storage.delete_find_image_objects(
            user_id="user-1",
            find_id="find-1",
            storage_ref=storage_ref,
        )
