"""小影 API 友情链接服务

职责：后端统一拉取小影 API 的友情链接，缓存 1 小时，供全站模板（页脚）与
      外链替换中间件（Web/middleware.py）共用。

关键约束：链接必须在服务端抓取并渲染进 HTML（搜索引擎直接可见），
          绝不通过前端 JS 请求 API（爬虫执行不到 JS，会漏掉链接）。

失败处理：拉取失败时保留上一次的缓存（不覆盖），避免一次网络抖动让全站友情链接
          消失一小时；从未成功拉取过时返回空列表，页面照常渲染。
"""
import logging

from django.core.cache import cache

from API.common.signature import signed_get

logger = logging.getLogger(__name__)

# 友情链接接口路径（status=true 只返回启用状态的链接）
FRIEND_LINKS_PATH = '/api/seo/friend_links'
# 缓存键与有效期（1 小时，降低小影 API 压力）
CACHE_KEY = 'xyapi:friend_links'
CACHE_TTL = 60 * 60


def _fetch_links():
    """从小影 API 拉取并过滤友情链接

    返回链接列表；**拉取失败返回 None**，用来区别于"接口正常、但一条链接都没有"的 []。
    """
    try:
        payload = signed_get(FRIEND_LINKS_PATH, {'status': 'true'})
        items = (payload.get('data') or {}).get('items') or []
        links = []
        for item in items:
            name = (item.get('name') or '').strip()
            url = (item.get('url') or '').strip()
            # 过滤规则：名称非空、状态启用、http(s) 链接、url 不含属性注入字符
            if not name or not url:
                continue
            if item.get('status') is False:
                continue
            if not (url.startswith('http://') or url.startswith('https://')):
                continue
            if any(ch in url for ch in '\'"<>'):
                continue
            links.append({'name': name, 'url': url})
        return links
    except Exception:
        logger.exception('拉取小影 API 友情链接失败')
        return None


def get_friend_links():
    """获取友情链接列表（缓存 1 小时），失败时回落到上一次缓存或空列表"""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    links = _fetch_links()
    if links is not None:
        cache.set(CACHE_KEY, links, CACHE_TTL)
        return links
    return cache.get(CACHE_KEY) or []


def friend_links(request):
    """Django context processor：向全站模板注入 friend_links 变量"""
    return {'friend_links': get_friend_links()}
