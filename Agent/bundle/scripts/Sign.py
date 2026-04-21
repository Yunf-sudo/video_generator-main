import datetime
import hashlib
import hmac
from urllib.parse import quote


def norm_query(params: dict):
    query = ""
    for key in sorted(params.keys()):
        if type(params[key]) == list:
            for k in params[key]:
                query = (
                        query + quote(key, safe="-_.~") + "=" + quote(k, safe="-_.~") + "&"
                )
        else:
            query = (query + quote(key, safe="-_.~") + "=" + quote(params[key], safe="-_.~") + "&")
    query = query[:-1]
    return query.replace("+", "%20")


# 第一步：准备辅助函数。
# sha256 非对称加密
def hmac_sha256(key: bytes, content: str):
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()


# sha256 hash算法
def hash_sha256(content: str):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# 第二步：签名请求函数
def get_authorization(method, headers, query, service, region, ak, sk):
    # 第三步：创建身份证明。其中的 Service 和 Region 字段是固定的。ak 和 sk 分别代表
    # AccessKeyID 和 SecretAccessKey。同时需要初始化签名结构体。一些签名计算时需要的属性也在这里处理。
    # 初始化身份证明结构体
    credential = {
        "access_key_id": ak,
        "secret_access_key": sk,
        "service": service,
        "region": region,
    }
    # 初始化签名结构体
    # request_param = {
    #     "body": body,
    #     "host": headers['Host'],
    #     "path": "/",
    #     "method": method,
    #     "content_type": headers['Content-Type'],
    #     "query": {"Action": action, "Version": version, **query},
    # }
    # if body is None:
    #     request_param["body"] = ""
    # 第四步：接下来开始计算签名。在计算签名前，先准备好用于接收签算结果的 signResult 变量，并设置一些参数。
    # 初始化签名结果的结构体
    x_date = headers['X-Date']
    short_x_date = x_date[:8]
    x_content_sha256 = headers['X-Content-Sha256']
    # sign_result = {
    #     "Host": request_param["host"],
    #     "X-Content-Sha256": x_content_sha256,
    #     "X-Date": x_date,
    #     "Content-Type": request_param["content_type"],
    # }
    # 第五步：计算 Signature 签名。
    signed_headers_str = ";".join(
        ["content-type", "host", "x-content-sha256", "x-date"]
    )
    # signed_headers_str = signed_headers_str + ";x-security-token"
    canonical_request_str = "\n".join(
        [method,
         '/',
         norm_query(query),
         "\n".join(
             [
                 "content-type:" + headers['Content-Type'],
                 "host:" + headers["Host"],
                 "x-content-sha256:" + x_content_sha256,
                 "x-date:" + x_date,
             ]
         ),
         "",
         signed_headers_str,
         x_content_sha256,
         ]
    )

    # 打印正规化的请求用于调试比对
    print(f"canonical_request_str:{canonical_request_str}")
    hashed_canonical_request = hash_sha256(canonical_request_str)

    # 打印hash值用于调试比对
    print(f"hashed_canonical_request:{hashed_canonical_request}")
    credential_scope = "/".join([short_x_date, credential["region"], credential["service"], "request"])
    string_to_sign = "\n".join(["HMAC-SHA256", x_date, credential_scope, hashed_canonical_request])

    # 打印最终计算的签名字符串用于调试比对
    print(f"{string_to_sign}")
    k_date = hmac_sha256(credential["secret_access_key"].encode("utf-8"), short_x_date)
    k_region = hmac_sha256(k_date, credential["region"])
    k_service = hmac_sha256(k_region, credential["service"])
    k_signing = hmac_sha256(k_service, "request")
    signature = hmac_sha256(k_signing, string_to_sign).hex()

    return "HMAC-SHA256 Credential={}, SignedHeaders={}, Signature={}".format(
        credential["access_key_id"] + "/" + credential_scope,
        signed_headers_str,
        signature,
    )


def get_x_date(date=datetime.datetime.now(datetime.timezone.utc)):
    return date.strftime("%Y%m%dT%H%M%SZ")


def get_url(host, path, action, version):
    return f"https://{host}{path}?Action={action}&Version={version}"
