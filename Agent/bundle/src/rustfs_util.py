import os
from agent_bundle_env import load_agent_bundle_env
import uuid

from media_pipeline import copy_to_local_storage, safe_file_uri

try:
    import boto3
    from botocore.client import Config
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None
    Config = None

load_agent_bundle_env()

s3 = (
    boto3.client(
        's3',
        endpoint_url=os.getenv('RUSTFS_ENDPOINT'),
        aws_access_key_id=os.getenv('RUSTFS_ACCESS_KEY'),
        aws_secret_access_key=os.getenv('RUSTFS_ACCESS_SECRET'),
        config=Config(signature_version='s3v4'),
        region_name='us-east-1'
    )
    if boto3 is not None and Config is not None
    else None
)

def upload_file_to_rustfs(file_path: str, bucket_name: str, object_name: str = None, rename_file: bool = False) -> str:
    """
    上传文件 to RustFS (S3 compatible)
    :param file_path: 本地文件路径
    :param bucket_name: 存储桶名称
    :param object_name: 对象名称 (可选)
    :param rename_file: 是否使用UUID重命名文件
    :return: 下载链接
    """
    try:
        bucket_name = bucket_name or "local-media"
        if s3 is None:
            raise RuntimeError("boto3 is not installed for RustFS upload.")
        if rename_file:
            _, ext = os.path.splitext(file_path)
            object_name = f"{uuid.uuid4()}{ext}"
        elif object_name is None:
            object_name = os.path.basename(file_path)

        s3.upload_file(file_path, bucket_name, object_name)
        print(f"File {file_path} uploaded to RustFS: {bucket_name}/{object_name}")
        
        return get_rustfs_url(bucket_name, object_name, expiration=-1)
    except Exception as e:
        print(f"Failed to upload file {file_path} to RustFS: {str(e)}")
        local_url, _ = copy_to_local_storage(file_path, bucket_name, object_name=object_name or os.path.basename(file_path))
        return local_url

def get_rustfs_url(bucket_name: str, object_name: str, expiration: int = 3600) -> str:
    """
    获取文件的预签名下载链接
    :param bucket_name: 存储桶名称
    :param object_name: 对象名称
    :param expiration: 过期时间 (秒)，如果为 -1 则生成不带签名的公共 URL
    :return: URL
    """
    try:
        if s3 is None:
            raise RuntimeError("boto3 is not installed for RustFS URL generation.")
        if expiration == -1:
            # Construct public URL manually assuming standard S3 path style or virtual host style
            # Using endpoint_url from s3 client configuration
            endpoint_url = s3.meta.endpoint_url
            if endpoint_url.endswith('/'):
                endpoint_url = endpoint_url[:-1]
            return f"{endpoint_url}/{bucket_name}/{object_name}"
        
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_name},
            ExpiresIn=expiration
        )
        return url
    except Exception as e:
        print(f"Failed to generate URL for {bucket_name}/{object_name}: {str(e)}")
        return ""
