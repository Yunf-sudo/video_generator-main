import os
from minio import Minio
from dotenv import load_dotenv
import uuid
import os
from datetime import datetime

load_dotenv()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")

client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

def upload_file_to_minio(file_path: str, bucket_name: str, object_name: str = None) -> str:
    try:
        _, ext = os.path.splitext(file_path)
        if object_name is None:
            # Generate random UUID with original extension
            object_name = f"{uuid.uuid4()}{ext}"
            # Create bucket if it doesn't exist
        # Append timestamp to the filename
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        name_part, ext_part = os.path.splitext(object_name)
        object_name = f"{name_part}_{timestamp}{ext_part}"
        # 添加正确的Content-Type
        content_type = None
        if ext.lower() in ['.mp4', '.mpeg4']:
            content_type = 'video/mp4'
        elif ext.lower() in ['.avi']:
            content_type = 'video/x-msvideo'
        elif ext.lower() in ['.mov']:
            content_type = 'video/quicktime'
        elif ext.lower() in ['.webm']:
            content_type = 'video/webm'
            
        # 上传时指定Content-Type
        client.fput_object(bucket_name, object_name, file_path, content_type=content_type)
        
        # 生成预签名URL时也指定响应头
        url = client.presigned_get_object(
            bucket_name, 
            object_name,
            response_headers={'response-content-type': content_type} if content_type else None
        )
        print(f"文件 {file_path} 上传到 MinIO 成功，对象名称: {object_name}")
        return url
    except Exception as e:
        print(f"文件 {file_path} 上传到 MinIO 失败: {str(e)}")
        return ""

if __name__ == "__main__":
    file_path = "/home/wzc/code/fengshuidemo/uploads/3e6bd8c0cf1aa53179e2a383975d647b.mp4"
    bucket_name = "test"
    object_name = "20230824162832.mp4"
    url = upload_file_to_minio(file_path, bucket_name, object_name)
    print(url)