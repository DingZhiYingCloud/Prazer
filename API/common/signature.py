"""小影 API 签名工具

职责：按小影 API 接入向导（/guide/）的口径生成签名并补全公共参数，
供 API/apis/ 下各接口客户端复用。

签名算法（与服务端必须一致）：
    1. 取除 sign 外的全部非空参数（含 app_id / timestamp / nonce 与业务参数）；
    2. 按键名 ASCII 升序排序，拼接为 key=value&key=value...；
    3. 以 APPSECRET 为密钥做 HMAC-SHA256，输出小写 hex 即为 sign。

公共参数：
    app_id     接入项目公开标识（app_ 开头）
    timestamp  10 位秒级时间戳，服务端有效窗口 ±5 分钟
    nonce      每次请求唯一（随机 16 位 hex），服务端按窗口去重防重放

注意：数组参数需自行拼成单值（如逗号分隔）再传入 —— requests 会把列表值
     拆成重复字段，而签名按单值计算，两边会对不上。
"""
import hashlib
import hmac
import os
import secrets
import time

import requests

# 小影 API 基础地址（.env 覆盖，切线上/本地只改 .env）
API_BASE = os.getenv('XIAOYING_API_BASE', 'https://xiaoyingapi.com')
# 接入项目凭证（未配置时不带签名，接口将返回 20011，由调用方降级处理）
APP_ID = os.getenv('XIAOYING_API_APPID', '')
APP_SECRET = os.getenv('XIAOYING_API_APPSECRET', '')

# 统一 UA：部分接口对 requests 的默认 UA 不友好
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
)

# 请求超时（秒）。取 4 秒：接口正常时都在几百毫秒内返回，而访客最多只该等这么久；
# 真遇上接口卡住，交给调用方用上一份缓存兜底（见 API/apis/movie.py 的 _cached），
# 不要用一个 10 秒的默认值把页面一起拖住。
REQUEST_TIMEOUT = 4


def sign_params(params):
    """生成签名（HMAC-SHA256，小写 hex）

    :param params: 含业务参数与公共参数（无需含 sign）的字典
    """
    items = sorted(
        (k, str(v)) for k, v in params.items()
        if k != 'sign' and v not in (None, '')
    )
    raw = '&'.join(f'{k}={v}' for k, v in items)
    return hmac.new(APP_SECRET.encode('utf-8'), raw.encode('utf-8'), hashlib.sha256).hexdigest()


def auth_params(business_params):
    """给业务参数补上签名公共参数（app_id / timestamp / nonce / sign）

    未配置凭证时原样返回业务参数，接口将返回 20011，由调用方降级处理。
    """
    params = dict(business_params)
    if not (APP_ID and APP_SECRET):
        return params
    params['app_id'] = APP_ID
    params['timestamp'] = str(int(time.time()))
    params['nonce'] = secrets.token_hex(8)
    params['sign'] = sign_params(params)
    return params


def signed_get(path, params=None, timeout=REQUEST_TIMEOUT):
    """带签名的 GET 请求，返回解析后的 JSON（是否成功由调用方判 code）

    :param path: 接口路径，如 /api/movies/movie_555/home
    :param params: 业务参数字典（签名公共参数由本函数自动补全）
    """
    resp = requests.get(
        f'{API_BASE}{path}',
        params=auth_params(params or {}),
        timeout=timeout,
        headers={'User-Agent': USER_AGENT},
    )
    resp.raise_for_status()
    return resp.json() or {}


def signed_post(path, params=None, timeout=REQUEST_TIMEOUT):
    """带签名的 POST 请求，返回解析后的 JSON（是否成功由调用方判 code）

    **同一份参数同时放在 query string 和请求体里**。这是实测结论，不是保守写法：
    海角线路下不同接口读参数的位置并不一致 ——
        /api/haijiao/register/captcha  只认 query string（放表单体返回 20001 参数缺失）
        /api/haijiao/login             只认表单体（放 query 返回 20001 参数缺失）
    两边都放、值完全一致，签名无论按哪一边校验都能对上，接口也不用一个一个去试。
    """
    signed = auth_params(params or {})
    resp = requests.post(
        f'{API_BASE}{path}',
        params=signed,
        data=signed,
        timeout=timeout,
        headers={'User-Agent': USER_AGENT},
    )
    resp.raise_for_status()
    return resp.json() or {}
