import json
import time

import requests

import Sign

STATUS_CODE_SUCCESS = 0

QUERY_STATUS_CODE_WAITING = 0
QUERY_STATUS_CODE_HANDING = 1
QUERY_STATUS_CODE_SUCCESS = 2
QUERY_STATUS_CODE_FAILED = 3


def get_response(response):
    response_json = json.loads(response.text)
    return response_json.get('Code'), response_json.get('Message'), response_json.get('Result'), response_json.get(
        'ResponseMetadata')


if __name__ == "__main__":
    ak = ""
    sk = ""
    text = "现代感十足的商业广告配乐"
    genre = ["corporate"]
    mood = ["peaceful",'soft']
    Instrument=['piano','strings']
    Theme = ["every day"]
    Duration = 5 # 单位：秒，范围：[1,60]

    action = "GenBGM"
    version = "2024-08-12"
    region = "cn-beijing"
    service = 'imagination'
    host = "open.volcengineapi.com"
    path = "/"
    query = {'Action': action,
             'Version': version}
    body = {
        'Text': text,
        'Theme': Theme,
        'Genre': genre,
        'Mood': mood,
        'Instrument': Instrument,
        'Duration': Duration,
    }
    x_content_sha256 = Sign.hash_sha256(json.dumps(body))
    headers = {"Content-Type": 'application/json',
               'Host': host,
               'X-Date': Sign.get_x_date(),
               'X-Content-Sha256': x_content_sha256
               }
    authorization = Sign.get_authorization("POST", headers=headers, query=query, service=service, region=region, ak=ak,
                                           sk=sk)
    print(f"===>authorization:{authorization}")

    headers["Authorization"] = authorization

    response = requests.post(Sign.get_url(host, path, action, version), data=json.dumps(body), headers=headers)
    print(f"===>Response:{response.text}")
    # 查询歌曲生成信息
    code, message, result, ResponseMetadata = get_response(response)
    if code != STATUS_CODE_SUCCESS or not response.ok:
        raise RuntimeError(response.text)
    taskId = result['TaskID']
    predictedWaitTime =  5  # 预计等待生成音乐需要的时间，单位：s
    print('===>waiting...')
    time.sleep(predictedWaitTime)
    body = {'TaskID': taskId}
    x_content_sha256 = Sign.hash_sha256(json.dumps(body))
    headers['X-Content-Sha256'] = x_content_sha256
    headers['X-Date'] = Sign.get_x_date()
    action = 'Query'
    query["Action"] = action
    authorization = Sign.get_authorization("POST", headers=headers, query=query, service=service, region=region, ak=ak,
                                           sk=sk)
    print(f"===>authorization:{authorization}")

    headers["Authorization"] = authorization
    songDetail = None
    while True:
        response = requests.post(Sign.get_url(host, path, action, version), data=json.dumps(body), headers=headers)
        print(response.text)
        if not response.ok:
            raise RuntimeError(response.text)

        code, message, result, ResponseMetadata = get_response(response)
        progress = result.get('Progress')
        status = result.get('Status')

        if status == QUERY_STATUS_CODE_FAILED:
            raise RuntimeError(response.text)
        elif status == QUERY_STATUS_CODE_SUCCESS:
            songDetail = result.get('SongDetail')
            print(f"===>query finished:{progress}")
            break
        elif status == QUERY_STATUS_CODE_WAITING or status == QUERY_STATUS_CODE_HANDING:
            print(f"===>Progress:{progress}")
            # 间隔一定时间再查询
            time.sleep(5)
        else:
            print(response.text)
            break

    if songDetail is not None:
        audioUrl = songDetail.get('AudioUrl')
        print(f"===>AudioUrl:{audioUrl}")
