from s3 import get_r2_client
import os
from dotenv import load_dotenv

load_dotenv()

def upload_file(
    file_path: str,
    key: str,
    content_type: str = "video/mp4"
):
    r2 = get_r2_client()

    r2.upload_file(
        Filename=file_path,
        Bucket=os.getenv("R2_BUCKET_NAME"),
        Key=key,
        ExtraArgs={
            "ContentType": content_type
        }
    )

    return {
        "bucket": os.getenv("R2_BUCKET_NAME"),
        "key": key,
    }

def delete_file(key: str):
    r2 = get_r2_client()

    r2.delete_object(
        Bucket=os.getenv("R2_BUCKET_NAME"),
        Key=key,
    )

    return {"deleted": key}

def generate_presigned_upload_url(
    key: str,
    content_type: str = "video/mp4",
    expiration: int = 3600,
):
    r2 = get_r2_client()

    print('JJ LETS FIGURE THIS OUT', os.getenv("R2_BUCKET_NAME"), key, content_type)

    url = r2.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": os.getenv("R2_BUCKET_NAME"),
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expiration,
    )

    return url
