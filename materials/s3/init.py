"""Idempotent bucket bootstrap for an S3-compatible server (RustFS in dev).

Creates the bucket, its CORS rules (browser uploads with presigned PUT, and reads with
Range for the PDF reader of the library and sp apps) and the lifecycle rules. Needs
``aiobotocore``. Environment: S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET,
S3_CORS_ORIGINS (comma separated).
"""

import asyncio
import os

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import ClientError

EXISTS = {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}


async def main() -> None:
    """Create the bucket, then apply CORS and lifecycle configuration."""
    config = AioConfig(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        connect_timeout=5,
        retries={"max_attempts": 5, "mode": "standard"},
    )
    bucket = os.environ["S3_BUCKET"]
    async with get_session().create_client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name="us-east-1",
        config=config,
    ) as s3:
        try:
            await s3.create_bucket(Bucket=bucket)
            await s3.put_bucket_cors(
                Bucket=bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": os.environ["S3_CORS_ORIGINS"].split(","),
                            "AllowedMethods": ["GET", "HEAD", "PUT"],
                            "AllowedHeaders": ["*"],
                            # The readers (library, sp) load books with HTTP Range requests
                            # and need the range headers of the answer.
                            "ExposeHeaders": [
                                "ETag",
                                "x-amz-checksum-sha256",
                                "Accept-Ranges",
                                "Content-Range",
                                "Content-Length",
                            ],
                            "MaxAgeSeconds": 3600,
                        }
                    ]
                },
            )
            await s3.put_bucket_lifecycle_configuration(
                Bucket=bucket,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "ID": "abort-stale-multipart",
                            "Status": "Enabled",
                            "Filter": {"Prefix": ""},
                            "AbortIncompleteMultipartUpload": {
                                "DaysAfterInitiation": 1
                            },
                        },
                        {
                            "ID": "expire-tmp",
                            "Status": "Enabled",
                            "Filter": {"Prefix": "tmp/"},
                            "Expiration": {"Days": 1},
                        },
                    ]
                },
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in EXISTS:
                print("S3 Initialization error:", exc)


if __name__ == "__main__":
    asyncio.run(main())
