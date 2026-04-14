"""Cloudflare R2 helpers for presigned image uploads."""

import os
from functools import lru_cache
from typing import Dict, List

import boto3


R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "").strip()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET = os.getenv("R2_BUCKET", "").strip()
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
R2_UPLOAD_EXPIRATION_SECONDS = int(os.getenv("R2_UPLOAD_EXPIRATION_SECONDS", "600"))
R2_S3_ENDPOINT = os.getenv("R2_S3_ENDPOINT", "").strip()


def is_r2_configured() -> bool:
    return all([
        R2_ACCOUNT_ID,
        R2_ACCESS_KEY_ID,
        R2_SECRET_ACCESS_KEY,
        R2_BUCKET,
        R2_PUBLIC_BASE_URL,
    ])


def _endpoint_url() -> str:
    if R2_S3_ENDPOINT:
        return R2_S3_ENDPOINT
    return f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


@lru_cache(maxsize=1)
def get_r2_client():
    if not is_r2_configured():
        raise RuntimeError("R2 storage is not fully configured")

    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(),
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _public_url_for_key(object_key: str) -> str:
    return f"{R2_PUBLIC_BASE_URL}/{object_key}"


def generate_find_image_upload_plans(
    *,
    user_id: str,
    find_id: str,
    image_ids: List[str],
) -> List[Dict[str, str]]:
    if not is_r2_configured():
        raise RuntimeError("R2 storage is not configured")

    client = get_r2_client()
    plans: List[Dict[str, str]] = []

    for image_id in image_ids:
        safe_image_id = "".join(
            ch for ch in image_id if ch.isalnum() or ch in {"-", "_"}
        )[:80]
        if not safe_image_id:
            raise RuntimeError("Invalid image id for upload")

        base_ref = f"finds/{user_id}/{find_id}/{safe_image_id}"
        thumbnail_key = f"{base_ref}_thumb.jpg"
        full_key = f"{base_ref}_full.jpg"

        thumbnail_upload_url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": R2_BUCKET,
                "Key": thumbnail_key,
                "ContentType": "image/jpeg",
            },
            ExpiresIn=R2_UPLOAD_EXPIRATION_SECONDS,
        )
        full_upload_url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": R2_BUCKET,
                "Key": full_key,
                "ContentType": "image/jpeg",
            },
            ExpiresIn=R2_UPLOAD_EXPIRATION_SECONDS,
        )

        plans.append(
            {
                "imageId": safe_image_id,
                "storageRef": base_ref,
                "thumbnailUploadUrl": thumbnail_upload_url,
                "fullUploadUrl": full_upload_url,
                "thumbnailUrl": _public_url_for_key(thumbnail_key),
                "fullUrl": _public_url_for_key(full_key),
            }
        )

    return plans
