"""图片代理：把第三方海报换成本站地址（本地缓存 + 压缩）

为什么需要：
    全站海报都来自第三方（百度图床 / 源站域名），实测对方会时不时连不上
    （ERR_CONNECTION_CLOSED），防盗链、限速、图片体积也都不可控。
    这里做一层"取一次、存本地、之后发本地文件"的代理。

访问方式（由模板标签 xy_pic.pic 生成）：
    /pic/<签名>.webp?u=<原图地址，URL 编码>

处理顺序：
    1. 校验签名（HMAC，密钥取 SECRET_KEY）——不通过直接 404，
       避免被陌生人当成免费图床或内网探测跳板；
    2. 本地已有该图 → 直接发（带 30 天缓存头）；
    3. 没有 → 回源下载一次 → 压成 webp、超过最大宽度就等比缩小 → 存盘再发；
    4. 回源失败 → 302 到原图地址，让访客浏览器按老办法直接去取。
       即"最差也不比不代理更糟"，不会出现"本来能看、加了代理反而看不了"；
       同时把这个地址记进"失败记忆"（10 分钟），期间不再重复回源 ——
       源站已挂掉时（实测 5dy4.vip），否则每次页面浏览都要占着 worker 干等十几秒。

磁盘占用：按文件数量滚动淘汰（超过上限时删掉最老的 20%，最多每 10 分钟检查一次），
         不引入定时任务，也不会把磁盘吃满。

依赖：Pillow（WebP 编码需要 Pillow 带 webp 支持，官方轮子默认包含）。
"""
import hashlib
import hmac
import io
import logging
import os
import time
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.http import http_date
from PIL import Image

logger = logging.getLogger(__name__)

# 本地存放目录（放在 MEDIA_ROOT 下，与站点其它图片一致）
PIC_DIR = os.path.join(settings.MEDIA_ROOT, 'pic')
# 图片最大宽度：首屏大图在 2 倍屏上也够清晰，卡片图更绰绰有余
MAX_WIDTH = 1080
# webp 质量（82 在肉眼几乎无损的前提下能省掉一大半体积）
WEBP_QUALITY = 82
# 回源超时与单张体积上限（超过视为异常，放弃转换，直接放行原图）
# 拆成"连接 3 秒 / 读取 8 秒"：源站已经挂掉时（实测 5dy4.vip 就是），连接失败能很快返回，
# 不会让每个访客的每次页面浏览都占着一个 worker 干等十几秒。
REQUEST_TIMEOUT = (3, 8)
MAX_BYTES = 8 * 1024 * 1024
# 失败记忆：同一个地址刚失败过就不要再试，直接按"回源失败"处理；
# 只是短期记忆（10 分钟），避免源站恢复后一直不肯再拉。
FAIL_SUFFIX = 'xypic:fail'
FAIL_TTL = 600
# 本地图片数量上限与淘汰比例
MAX_FILES = 4000
CULL_KEEP_RATIO = 0.8
# 淘汰检查的最小间隔（秒），避免每次请求都去数目录
CULL_INTERVAL = 600
# 浏览器缓存时长（30 天，图片内容按 URL 固定，不需要频繁回验）
CACHE_SECONDS = 30 * 24 * 3600
# 回源请求头：部分图床对默认 UA 不友好
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
)
_CULL_LOCK_KEY = 'xypic:cull'


def sign(url):
    """对原图地址签名：只有本站生成过的图片地址才会被代理"""
    return hmac.new(
        settings.SECRET_KEY.encode('utf-8'), url.encode('utf-8'), hashlib.sha256
    ).hexdigest()[:20]


def pic_url(url):
    """把原图地址换成本站代理地址

    - 空值、以及本站自己的 /media/ 图片原样返回；
    - 其余一律走 /pic/<签名>.webp?u=<编码后的原图地址>。
    """
    url = (url or '').strip()
    if not url or url.startswith('/'):
        return url
    if not url.startswith(('http://', 'https://')):
        return url
    return f'/pic/{sign(url)}.webp?u={quote(url, safe="")}'


def _key(url):
    """本地文件名：由原图地址算哈希（不接受外部指定，避免覆盖别人的缓存）"""
    return hashlib.sha1(url.encode('utf-8')).hexdigest()[:24]


def _local_path(url):
    return os.path.join(PIC_DIR, f'{_key(url)}.webp')


def _download(url):
    """回源取图 bytes；失败或体积/类型异常返回 None（并记下失败，短期不再重试）"""
    try:
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT, headers={'User-Agent': USER_AGENT},
            stream=True,
        )
        resp.raise_for_status()
        if 'image' not in (resp.headers.get('Content-Type') or ''):
            return None
        data = resp.raw.read(MAX_BYTES + 1, decode_content=True)
    except Exception:
        logger.warning('图片代理回源失败: %s', url)
        cache.set(FAIL_SUFFIX + _key(url), 1, FAIL_TTL)
        return None
    if not data or len(data) > MAX_BYTES:
        return None
    return data


def _to_webp(data):
    """转成 webp（必要时等比缩小）；失败返回 None"""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
        if img.width > MAX_WIDTH:
            height = max(1, round(img.height * MAX_WIDTH / img.width))
            img = img.resize((MAX_WIDTH, height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, 'WEBP', quality=WEBP_QUALITY, method=4)
        return buf.getvalue()
    except Exception:
        logger.warning('图片代理转码失败，将直接放行原图')
        return None


def _cull():
    """按数量上限滚动淘汰本地图片（节流执行，失败不影响正常出图）"""
    if not cache.add(_CULL_LOCK_KEY, 1, CULL_INTERVAL):
        return
    try:
        names = [os.path.join(PIC_DIR, n) for n in os.listdir(PIC_DIR)]
    except OSError:
        return
    # 会与 .webp 一起列出临时文件等，统一按"文件"处理，出错逐个跳过
    if len(names) <= MAX_FILES:
        return
    names.sort(key=lambda p: (os.path.getmtime(p), p))
    for path in names[: int(len(names) * (1 - CULL_KEEP_RATIO))]:
        try:
            os.remove(path)
        except OSError:
            pass


def _serve(data, content_type='image/webp'):
    resp = HttpResponse(data, content_type=content_type)
    resp['Cache-Control'] = f'public, max-age={CACHE_SECONDS}'
    resp['Expires'] = http_date(time.time() + CACHE_SECONDS)
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp


def pic(request, sig):
    """图片代理入口（路径与用法见模块开头说明）"""
    url = request.GET.get('u') or ''
    if not url.startswith(('http://', 'https://')):
        return HttpResponse(status=404)
    if not hmac.compare_digest(sig, sign(url)):
        return HttpResponse(status=404)

    path = _local_path(url)
    if os.path.exists(path):
        try:
            with open(path, 'rb') as fp:
                return _serve(fp.read())
        except OSError:
            pass

    # 刚失败过的地址直接跳过回源：少一次十几秒的干等，页面也不会因此变慢
    if cache.get(FAIL_SUFFIX + _key(url)):
        return HttpResponseRedirect(url)

    data = _download(url)
    webp = _to_webp(data) if data else None
    if webp is None:
        # 回源失败：交给浏览器直接去取原图（带上原协议跳转，避免 HTTPS 降级告警），
        # 那边再失败就由前端的图片兜底逻辑换成占位图
        return HttpResponseRedirect(url)

    try:
        os.makedirs(PIC_DIR, exist_ok=True)
        with open(path, 'wb') as fp:
            fp.write(webp)
        _cull()
    except OSError:
        # 磁盘不可写也要能把图发出去，只是这次不落盘（下次再试）
        pass
    return _serve(webp)
