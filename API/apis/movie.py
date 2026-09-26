"""小影 API 电影服务客户端（555 电影线路）

职责：封装 /api/movies/movie_555/* 六个接口的签名请求与结果缓存，
供 Web 视图层直接调用（接口全部为 GET，需签名）。

统一约定：
    - 成功返回接口响应中的 data（dict / list）；
    - 任何失败（网络异常 / code != 10000 / data 为空）均返回 None 并记录日志，
      由调用方做降级展示，不把异常抛给视图；
    - 结果按接口类型缓存（时长见 settings 的 XIAOYING_MOVIE_*_TTL）：
      数据类缓存较久，播放地址（m3u8 带时效）较短，与接口文档说明一致。

调用示例：
    from API.apis import movie

    categories = movie.get_categories()          # 分类/榜单列表
    filters = movie.get_filters(2)               # 该分类可用的筛选项（地区/题材/语言/年份…）
    items = movie.get_list(2, page=1, area='韩国', order='hits')
    detail = movie.get_detail(812640)            # sources[].episodes[].sid/nid
    play = movie.get_play(812640, sid=3, nid=1)  # play['m3u8']
"""
import html
import logging
import re

from django.conf import settings
from django.core.cache import cache

from API.common.signature import REQUEST_TIMEOUT, signed_get

logger = logging.getLogger(__name__)

# 线路基础路径
LINE_PATH = '/api/movies/movie_555'
# 小影 API 统一响应中表示成功的 code
SUCCESS_CODE = 10000
# 播放接口的超时：它要回源解析 m3u8，比数据接口慢得多（实测正常也要 0.7s，
# 且偶发几秒级的抖动）。给宽一点，宁可多等几秒也不要让访客撞上"页面不存在"。
PLAY_TIMEOUT = 10
# 缓存键前缀
CACHE_PREFIX = 'xyapi:movie'
# 陈旧兜底：每次成功取数都额外存一份长 TTL 的备份，接口临时不可用时拿它顶上。
# 访客看到的是"几小时前的旧数据"，总好过整页空白；TTL 只影响"最多能兜多久"。
STALE_SUFFIX = ':stale'
STALE_TTL = 7 * 24 * 3600

# 小影接口的部分文本字段会把 HTML 实体多层转义后直接返回（例如某条轮播简介结尾是
# "&amp;amp;    ; &amp;amp;"），Django 渲染时又会再转义一次，页面上就会看到 "&amp;" 这类残渣。
# 下面两个正则负责在取数时把这类垃圾清干净。
_ENTITY_JUNK_RE = re.compile(r'&[a-zA-Z]{0,10}\s*;')
# 多层反转义后可能剩下孤立的 "&"（原串末尾那截实体的分号被吃掉了），按"单词式 &"清掉；
# 这样不会误伤 AT&T 这类正常写法。
_LONE_AMP_RE = re.compile(r'(?:^|\s)&(?=\s|$)')
_WHITESPACE_RE = re.compile(r'\s+')


def clean_text(value):
    """清洗接口文案：反复反转义 HTML 实体 → 清掉剩下的实体空壳 → 压缩空白"""
    text = value
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    text = text.replace('\u00a0', ' ')
    text = _ENTITY_JUNK_RE.sub(' ', text)
    text = _LONE_AMP_RE.sub(' ', text)
    return _WHITESPACE_RE.sub(' ', text).strip()


def clean_payload(value):
    """递归清洗响应里的文本字段

    URL 原样放行：播放地址里带 "&" 的参数不能被反转义或压空白改写。
    """
    if isinstance(value, str):
        if value.startswith(('http://', 'https://')):
            return value
        return clean_text(value)
    if isinstance(value, dict):
        return {key: clean_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_payload(item) for item in value]
    return value


def _fetch(path, params=None, timeout=REQUEST_TIMEOUT):
    """请求接口并取 data；失败返回 None"""
    try:
        payload = signed_get(path, params, timeout=timeout)
    except Exception:
        logger.exception('小影电影接口请求失败: %s', path)
        return None
    if payload.get('code') != SUCCESS_CODE:
        logger.warning(
            '小影电影接口返回异常: %s code=%s msg=%s',
            path, payload.get('code'), payload.get('msg'),
        )
        return None
    return clean_payload(payload.get('data'))


def _cached(key, ttl, path, params=None, timeout=REQUEST_TIMEOUT):
    """带缓存的取数

    - 命中缓存直接返回；
    - 未命中则请求，**仅成功才写缓存** —— 失败（None）写进缓存会让页面在 TTL 内一直空，
      故不写，下次请求可重试；成功时同时写一份长 TTL 的"陈旧备份"；
    - 请求失败时回退陈旧备份：接口偶尔抽风不该让访客看到空白页。
    """
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = _fetch(path, params, timeout)
    if data is not None:
        cache.set(key, data, ttl)
        cache.set(key + STALE_SUFFIX, data, STALE_TTL)
        return data
    stale = cache.get(key + STALE_SUFFIX)
    if stale is not None:
        logger.warning('小影接口暂不可用，回退到旧数据: %s', path)
    return stale


def get_categories():
    """分类列表（主分类 / 榜单 / 专题）

    返回值中的 id 可传给 get_list 的 type_id。
    """
    return _cached(
        f'{CACHE_PREFIX}:categories',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/categories',
    )


def get_home():
    """首页聚合：轮播图与各推荐区块（本周/本月最佳、各榜单等）"""
    return _cached(
        f'{CACHE_PREFIX}:home',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/home',
    )


def get_list(type_id, page=1, order=None, year=None, area=None, genre=None, lang=None):
    """按分类获取影片列表，返回 {'items': [...], 'pagination': {...}}

    :param type_id: 分类/榜单 ID（必填，见 get_categories）
    :param page: 页码，从 1 开始
    :param order: 排序方式 time/hits/score
    :param year: 按年份筛选，如 2026
    :param area: 按地区筛选，如 大陆
    :param genre: 按题材筛选，如 动作
    :param lang: 按语言筛选，如 国语

    地区/题材/语言/年份可任意组合，源站按交集返回；可选值一律取自 get_filters，
    调用方不要自己造值（同一个值会占用一份缓存，也容易打到源站的空结果）。
    """
    params = {'type_id': type_id, 'page': page}
    for key, value in (('order', order), ('year', year), ('area', area),
                       ('genre', genre), ('lang', lang)):
        if value:
            params[key] = value
    key = (f'{CACHE_PREFIX}:list:{type_id}:{page}:{order or "-"}:{year or "-"}'
           f':{area or "-"}:{genre or "-"}:{lang or "-"}')
    return _cached(key, settings.XIAOYING_MOVIE_CACHE_TTL, f'{LINE_PATH}/list', params)


def get_filters(type_id):
    """某分类可用的筛选条件：{'type_id', 'sub_types': [...], 'groups': [...]}

    - sub_types：子分类，其 value 直接当作 type_id 传给 get_list（即子分类是独立列表页）；
    - groups：地区 / 题材 / 语言 / 年份 / 排序，其 options[].value 回传给 get_list 的同名参数。

    各分类的可用值不同（动漫有"日本/欧美"、综艺有"真人秀/脱口秀"），年份还会随上新增加，
    所以列表页的筛选栏必须由本接口动态渲染，不能在代码里写死。
    """
    return _cached(
        f'{CACHE_PREFIX}:filters:{type_id}',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/filters',
        {'type_id': type_id},
    )


def get_detail(vod_id):
    """影片详情：简介 / 导演演员等元数据 / 播放源与选集

    返回 data.sources（播放源），每个源的 episodes 里 sid/nid 用于 get_play。
    影片不存在时接口返回 40001，此处按失败处理返回 None。
    """
    return _cached(
        f'{CACHE_PREFIX}:detail:{vod_id}',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/detail',
        {'vod_id': vod_id},
    )


def get_play(vod_id, sid, nid):
    """播放地址：返回 data（含 m3u8 可播放地址，源站直出、带时效）

    :param vod_id: 影片 ID
    :param sid: 播放源序号，取自详情 sources[].sid
    :param nid: 集数序号，取自选集 episodes[].nid（电影通常为 1）
    """
    return _cached(
        f'{CACHE_PREFIX}:play:{vod_id}:{sid}:{nid}',
        settings.XIAOYING_MOVIE_PLAY_CACHE_TTL,
        f'{LINE_PATH}/play',
        {'vod_id': vod_id, 'sid': sid, 'nid': nid},
        timeout=PLAY_TIMEOUT,
    )


def get_search(keyword, page=1):
    """按关键词搜索影片，返回 data（含 results 影片列表与 pagination 总页数）

    :param page: 页码，从 1 开始

    返回的 data 形如：
        {'keyword': ..., 'page': 1, 'results': [...],
         'pagination': {'current': 1, 'total': 56}}
    注意 pagination.total 是**总页数**（与列表接口同口径），不是结果条数。
    """
    return _cached(
        f'{CACHE_PREFIX}:search:{keyword}:{page}',
        settings.XIAOYING_MOVIE_SEARCH_CACHE_TTL,
        f'{LINE_PATH}/search',
        {'keyword': keyword, 'page': page},
    )
