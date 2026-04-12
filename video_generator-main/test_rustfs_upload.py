import os
from rustfs_util import upload_file_to_rustfs

def test_rustfs():
    # Create a dummy file
    test_file = "test_upload.txt"
    with open(test_file, "w") as f:
        f.write("This is a test file for RustFS upload.")

    bucket_name = "test-bucket"  # Ensure this bucket exists or change to a valid one
    # If you don't know a valid bucket, you might need to list them first or just try this.
    # Assuming 'test-bucket' might not exist, let's try to rely on user's env or a known bucket if any.
    # But for now let's just use a placeholder and see if the code runs (it might fail on upload if bucket doesn't exist).
    
    # Actually, better to check if we can list buckets or just let the user know we are testing.
    # Let's try to upload.
    
    # Note: We need a bucket name. Since I don't have one from context, I'll use 'public' as a common default or check env.
    # Let's check env for a default bucket if possible, otherwise default to 'public'.
    bucket_name = os.getenv('RUSTFS_BUCKET', 'public') 

    print(f"Uploading {test_file} to bucket {bucket_name}...")
    url = upload_file_to_rustfs(test_file, bucket_name)
    
    if url:
        print(f"Upload successful! URL: {url}")
    else:
        print("Upload failed.")

    # Clean up
    if os.path.exists(test_file):
        os.remove(test_file)

if __name__ == "__main__":
    test_rustfs()
