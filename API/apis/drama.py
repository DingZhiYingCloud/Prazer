"""小影 API 短剧服务客户端（红果短剧线路）

职责：封装 /api/dramas/hongguo/* 五个接口的签名请求与结果缓存，
供 Web 视图层直接调用（接口全部为 GET，需签名）。

与 movie.py（555 电影线路）的关键差异：
    - 剧集用 series_id（长数字字符串）标识，不是 vod_id；
    - 详情一次返回**全量集号**，每集自带 playable 与 source 标记（接口已合并源站直链、
      已登记外链、服务端直出三条来源，所以它和「播放地址」接口的可用性一致）；
    - 播放地址有三种来源：前几集是源站明文 MP4 直链；第 4 集及以后优先给「已登记外链」
      （mp4 或 m3u8），没有登记则由接口侧「网页直出」（解密 + 转 H.264 的 MP4）。
      链接类型既有 mp4 也有 m3u8 —— 播放端两种都要能播，所以本站统一用 xgplayer；
    - 直出的集**首次点播时产物还在生成**（play 的 ready=False，实测约 25 秒），地址要轮询
      到出流成功才能播，播放页对此有专门的等待处理；
    - 集确实没有可用地址时接口返回 code=50002（msg 说明"正在扩展存储"）。这不是调用失败，
      而是"待上架"的正常占位 —— 所以不能套用 movie.py「非 10000 即失败」的判定，
      否则会把它当成接口错误（见 _fetch_raw 的说明）。

调用示例：
    from API.apis import drama

    categories = drama.get_categories()             # {'categories': [{slug, name, children}, ...]}
    items = drama.get_list('real-drama', page=1)    # {'results': [...], 'pagination': {...}}
    detail = drama.get_detail('7686894628578020414')
    play = drama.get_play('7686894628578020414', 2) # {'playable': True, 'url': ..., }
"""
import logging

from django.conf import settings
from django.core.cache import cache

from API.apis.movie import clean_payload
from API.common.signature import REQUEST_TIMEOUT, signed_get

logger = logging.getLogger(__name__)

# 线路基础路径
LINE_PATH = '/api/dramas/hongguo'
# 接口成功码
SUCCESS_CODE = 10000
# 「尚未上架」业务码：播放接口对第 4 集及以后尚未登记外链的集返回它
NOT_LISTED_CODE = 50002
# 播放接口超时：它要回源解析播放页 SSR，比数据接口慢，给宽一点
PLAY_TIMEOUT = 10
# 缓存键前缀
CACHE_PREFIX = 'xyapi:drama'
# 陈旧兜底：每次成功取数额外存一份长 TTL 备份，接口临时不可用时拿它顶上
STALE_SUFFIX = ':stale'
STALE_TTL = 7 * 24 * 3600


def _fetch_raw(path, params=None, timeout=REQUEST_TIMEOUT):
    """请求接口，原样返回 (code, data, msg)；网络异常返回 (None, None, 描述)

    刻意不在这里判定成功与否：短剧播放的「开发中」占位是 50002，调用方需要拿到它，
    不能像 movie.py 的 _fetch 那样把非 10000 一律当失败丢掉。
    """
    try:
        payload = signed_get(path, params, timeout=timeout)
    except Exception:
        logger.exception('小影短剧接口请求失败: %s', path)
        return None, None, '网络异常'
    return payload.get('code'), payload.get('data'), payload.get('msg')


def _cached_data(key, ttl, path, params=None, timeout=REQUEST_TIMEOUT):
    """数据类接口取数（榜单/分类/列表/详情）

    - 命中缓存直接返回；
    - 未命中则请求，**仅成功才写缓存** —— 失败写进缓存会让页面在 TTL 内一直空；
    - 请求失败时回退陈旧备份，接口偶尔抽风不该让访客看到空白页。
    """
    cached = cache.get(key)
    if cached is not None:
        return cached
    code, data, msg = _fetch_raw(path, params, timeout=timeout)
    if code == SUCCESS_CODE and data is not None:
        data = clean_payload(data)
        cache.set(key, data, ttl)
        cache.set(key + STALE_SUFFIX, data, STALE_TTL)
        return data
    if code is not None and code != SUCCESS_CODE:
        logger.warning('小影短剧接口返回异常: %s code=%s msg=%s', path, code, msg)
    stale = cache.get(key + STALE_SUFFIX)
    if stale is not None:
        logger.warning('小影短剧接口暂不可用，回退到旧数据: %s', path)
    return stale


def get_categories():
    """分类树：{'categories': [{'slug', 'name', 'url', 'children': [{...}]}]}

    两级结构：一级是内容形态（真人剧 / 漫剧 / AI剧 / 漫画），二级是题材。
    每个节点的 slug 都能直接传给 get_list：一级取该一级全部，二级只取该题材
    （二级取值形如 `real-drama/romance`，**带斜杠**）。

    **分类结构完全以接口返回为准**：调用方不要假设每个一级都有子级 ——
    漫画这类一级的 children 是空列表（本站的题材行会自动不显示）。
    """
    # 键带 v2：返回体由「扁平 4 项」改为「两级嵌套」是破坏性变更，沿用旧键会在 TTL
    # （6 小时）内继续下发旧结构 —— 读不到 children，二级地址会全部 404。
    # 换键让旧缓存自然失效，省掉一次"部署后必须手工清缓存"。
    return _cached_data(
        f'{CACHE_PREFIX}:categories:v2',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/categories',
    )


def get_list(category, page=1):
    """分类列表：{'category', 'page', 'results': [...], 'pagination': {'current', 'total'}}

    :param category: 分类 slug（见 get_categories）
    :param page: 页码，从 1 开始（站点每页 24 条）

    pagination.total 是**总页数**（与 555 列表接口同口径）。条目字段与榜单一致，
    只榜单专有的 rank/heat/score/favorite/like 恒为 None。
    """
    return _cached_data(
        f'{CACHE_PREFIX}:list:{category}:{page}',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/list',
        {'category': category, 'page': page},
    )


def get_search(keyword):
    """关键词搜索短剧：{'keyword', 'page', 'results': [...], 'pagination': {'current', 'total'}}

    红果源站的搜索**不支持分页**：接口对任何 page 都返回同一批（每页 10 条，
    pagination.total 恒为 1），所以这里不透出 page 参数，免得调用方以为能翻页。
    """
    return _cached_data(
        f'{CACHE_PREFIX}:search:{keyword}',
        settings.XIAOYING_MOVIE_SEARCH_CACHE_TTL,
        f'{LINE_PATH}/search',
        {'keyword': keyword},
    )


def get_detail(series_id):
    """剧集详情：{'series_id', 'name', 'cover', 'intro', 'tags', 'episode_cnt',
                  'playable_cnt', 'listed_cnt', 'external_cnt',
                  'episodes': [{'ep', 'episode_id', 'playable', 'source'}]}

    episodes 是**全量集号**（长度等于 episode_cnt）；playable 已合并接口侧的全部来源，
    每条还带 source 标出走的哪条路：
        origin    源站明文直链（前若干集）
        external  已登记的外部播放地址
        stream    接口侧「网页直出」（按需解密 + 转 H.264，见 get_play 的 ready）
    为 False 表示该集确实没有可用播放地址，与 get_play 的可用性一致。

    三个计数含义不同，别混用：
        playable_cnt  源站直链的**连续**范围（前 N 集），用它可以推算"前几集免转码"
        listed_cnt    **实际可播集数**（= playable 为真的集数），展示"能看几集"用它
        external_cnt  已登记外部链接的集数（人工上架进度），与能否播放无关

    剧集不存在时接口返回 40001，此处按失败处理返回 None。
    """
    return _cached_data(
        f'{CACHE_PREFIX}:detail:{series_id}',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/detail',
        {'series_id': series_id},
    )


def get_play(series_id, ep):
    """某集播放地址

    返回三种结果，调用方据此区分展示：
        可播     {'playable': True, 'url', 'source', 'url_type', 'ready', ...}
                 source 标出来源：origin 不带该字段（源站明文 MP4 直链）；
                 external 是已登记的第三方地址（mp4 / m3u8）；
                 stream 是接口侧直出（url 为接口域的绝对地址，带时效令牌，url_type 恒为 mp4）。
                 stream 才有 ready/quality：ready 为 False 表示该集该画质的产物还在生成
                 （首次点播约数十秒），此时地址会回 202，需轮询到出流成功再交给播放器。
        未上架   {'playable': False, 'status': 'not_listed'}
        取不到   None（接口异常、剧集不存在或集号越界）

    可播结果按播放缓存 TTL 缓存；「未上架」占位与 ready=False 的直出地址**都不写缓存** ——
    前者登记/上架后要立刻反映，后者是转码过程中的瞬时状态，缓存住会让后续访客多等一个 TTL。
    """
    key = f'{CACHE_PREFIX}:play:{series_id}:{ep}'
    cached = cache.get(key)
    if cached is not None:
        return cached

    code, data, msg = _fetch_raw(
        f'{LINE_PATH}/play', {'series_id': series_id, 'ep': ep}, timeout=PLAY_TIMEOUT,
    )
    if code == SUCCESS_CODE and isinstance(data, dict):
        data = clean_payload(data)
        if data.get('ready') is not False:
            cache.set(key, data, settings.XIAOYING_MOVIE_PLAY_CACHE_TTL)
        return data
    if code == NOT_LISTED_CODE:
        # 第 4 集及以后：源站只给 DRM 加密的 H.265，接口侧改由外部托管或网页直出，
        # 该集还没有可用地址（直出未启用、或转码已失败）
        return {'playable': False, 'status': 'not_listed'}
    if code is not None:
        logger.warning('小影短剧播放接口返回异常: series_id=%s ep=%s code=%s msg=%s',
                       series_id, ep, code, msg)
    return None
