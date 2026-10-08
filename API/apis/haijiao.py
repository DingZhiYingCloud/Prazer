"""小影 API 海角社区服务客户端

职责：封装 /api/haijiao/* 接口的签名请求与结果缓存，供 Web 视图层直接调用。

一、公开只读（本站频道页用）
    get_topics(tab, page)            内容列表（热帖/新闻/大事记/原创/精华/最新）
    get_search(keyword, page)        关键词搜索
    get_topic_detail(topic_id)       帖子详情（含正文/图片/视频附件/相关推荐）
    get_comments(topic_id, page)     主评论列表
    get_replies(comment_id, page)    二级评论列表
    get_gifts(kind, page)            打赏礼物清单
    get_video_m3u8(topic_id, aid)    可直播 m3u8（已还原真密钥，需凭据）

二、账号（注册 / 登录）
    get_register_captcha()           取注册图形验证码（需人工识别）
    get_register_credentials()       生成一组注册凭据（用户名/密码/邮箱）
    register(...)                    提交注册（会在源站真实建号）
    login(username, password)        账号登录，返回 token

三、必须带登录态（直传 user_id + user_token，均不缓存）
    get_user_info(...)               用户主页资料（查别人也可用）
    get_wealth(...)                  金币 / 钻石余额
    get_wealth_log(...)              金币 / 钻石流水
    get_my_topics(...)               我的帖子（按审核状态分 tab）
    get_liked_topics(...)            我点赞过的帖子
    get_favorite_folders(...)        我的收藏夹
    get_favorite_topics(...)         我收藏的帖子（可按收藏夹筛选）
    add_favorite(...)                收藏帖子（可指定收藏夹，缺省=默认夹）
    delete_favorite(...)             取消收藏帖子
    add_favorite_folder(...)         新建收藏夹
    rename_favorite_folder(...)      重命名收藏夹
    delete_favorite_folder(...)      删除收藏夹（源站要求夹内为空）
    get_following(...) / get_fans(...)  我关注的人 / 我的粉丝
    sign_in(...)                     每日签到
    like_topic(...)                  点赞 / 取消点赞
    get_like_state(...)              我有没有赞过这个帖子
    follow_user(...)                 关注 / 取消关注
    give_gift(...)                   打赏（真实扣费）

视频播放接口特性（与其它接口不同）：
    /api/haijiao/video/m3u8 在服务端已开放、不参与签名校验；它返回的是 m3u8
    播放列表文本（不是 JSON），签名客户端走的是 JSON 解析，所以这里走裸
    requests.get；同时按文档要求带 user_id + user_token（从 .env 读）。

调用示例：
    from API.apis import haijiao

    topics  = haijiao.get_topics('hot', page=1)
    detail  = haijiao.get_topic_detail('2271652')
    play    = haijiao.get_video_m3u8('2271635', '14141834')   # -> m3u8 文本
    data, msg = haijiao.login('xy_abc123456', 'Passw0rd12')   # -> (data, msg)
"""
import logging
import os

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _lazy

from API.apis.movie import clean_payload
from API.common.signature import (API_BASE, REQUEST_TIMEOUT, USER_AGENT,
                                 signed_get, signed_post)

logger = logging.getLogger(__name__)

LINE_PATH = '/api/haijiao'
SUCCESS_CODE = 10000
CACHE_PREFIX = 'xyapi:haijiao'
# 陈旧兜底：与 drama.py / movie.py 同款
STALE_SUFFIX = ':stale'
STALE_TTL = 7 * 24 * 3600
# 视频接口超时：源站拉 m3u8 并还原密钥比数据接口慢，给宽一点
VIDEO_TIMEOUT = 10
# 需要登录态的接口比只读接口慢，超时给宽一点
AUTH_TIMEOUT = 10


def _fetch_raw(path, params=None, timeout=REQUEST_TIMEOUT):
    """请求接口原样返回 (code, data, msg)；网络异常返 (None, None, 描述)

    不在这里判成功：与 drama.py 一致，把 code 透出去给调用方。
    """
    try:
        payload = signed_get(path, params, timeout=timeout)
    except Exception:
        logger.exception('小影海角接口请求失败: %s', path)
        return None, None, '网络异常'
    return payload.get('code'), payload.get('data'), payload.get('msg')


def _cached_data(key, ttl, path, params=None, timeout=REQUEST_TIMEOUT):
    """数据类取数：topics / search / detail / comments / replies / nodes"""
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
        logger.warning('小影海角接口返回异常: %s code=%s msg=%s', path, code, msg)
    stale = cache.get(key + STALE_SUFFIX)
    if stale is not None:
        logger.warning('小影海角接口暂不可用，回退旧数据: %s', path)
    return stale


# 内容列表栏目（接口允许的取值，非法返回 PARAM_VALUE_INVALID）
# 展示文案用 gettext_lazy：模块导入时还不能确定语言，真正的翻译在渲染时按当前语言求值。
TABS = ('hot', 'news', 'events', 'original', 'essence', 'latest')
TAB_LABELS = {
    'hot': _lazy('热帖'), 'news': _lazy('新闻'), 'events': _lazy('大事记'),
    'original': _lazy('原创'), 'essence': _lazy('精华'), 'latest': _lazy('最新'),
}


def get_topics(tab='hot', page=1):
    """内容列表：返回 {'tab', 'results': [...], 'pagination': {...}}

    :param tab: 栏目（hot/news/events/original/essence/latest），非法值接口返回错误。
    :param page: 页码从 1 起，源站每页 20 条。

    每条帖子含 topic_id / title / excerpt / node / tags / author / images / has_video
    / money_type / view_count / comment_count / like_count / create_time / last_comment_time。
    images 是源站混淆地址（需走 /api/haijiao/image 拿真实图片）；
    author.avatar / avatar_encrypted 含义见 API 文档。
    """
    return _cached_data(
        f'{CACHE_PREFIX}:topics:{tab}:{page}',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/topics',
        {'tab': tab, 'page': page},
    )


def get_search(keyword, page=1):
    """关键词搜索：返回 {'keyword', 'results': [...], 'pagination': {...}}

    :param keyword: 关键词（接口参数名是 key，不是 keyword）。
    :param page: 页码从 1 起，源站每页 20 条。

    该接口支持分页（实测 total_page 可达数百页），返回的 pagination 结构与
    topics 一致，可直接喂给 Web 层分页器。
    """
    return _cached_data(
        f'{CACHE_PREFIX}:search:{keyword}:{page}',
        settings.XIAOYING_MOVIE_SEARCH_CACHE_TTL,
        f'{LINE_PATH}/search',
        {'key': keyword, 'page': page},
    )


def get_topic_detail(topic_id):
    """帖子详情：返回 {'topic_id', 'title', ..., 'content'(HTML),
                     'images', 'videos': [{'id', 'url', 'play_url', ...}],
                     'has_video', 'author', 'related': [...], ...}

    videos[].url 是源站原始 m3u8（密钥是假的，不能直接播）；
    videos[].play_url 才是本站可播的 m3u8（接口已还原真密钥），它等于
    调用 get_video_m3u8(topic_id, videos[].id)。本站统一用 play_url，
    没拿到就降级为占位。
    """
    return _cached_data(
        f'{CACHE_PREFIX}:topic_detail:{topic_id}',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/topic/detail',
        {'topic_id': topic_id},
    )


def get_comments(topic_id, page=1):
    """主评论列表：返回 {'topic_id', 'results': [...], 'pagination': {...}}

    倒序（最新在前）。源站字段结构见 API 文档。
    """
    return _cached_data(
        f'{CACHE_PREFIX}:comments:{topic_id}:{page}',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/topic/comments',
        {'topic_id': topic_id, 'page': page},
    )


def get_replies(comment_id, page=1):
    """二级评论列表：返回 {'comment_id', 'results': [...], 'pagination': {...}}

    扁平结构：层级关系靠 root_comment_id / parent_comment_id 两个 ID 自组装。
    """
    return _cached_data(
        f'{CACHE_PREFIX}:replies:{comment_id}:{page}',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/comment/replies',
        {'comment_id': comment_id, 'page': page},
    )


def get_video_m3u8(topic_id, attachment_id):
    """视频播放 m3u8 文本（已还原源站真密钥，可直接交给 hls.js）

    接口默认"不参与签名校验"，返回的是 m3u8 文本（不是 JSON），所以这里走
    裸 requests.get；同时按文档要求带 user_id + user_token（从 .env 读）。

    返回值：
        成功 —— m3u8 文本（str）
        凭据缺失 —— None（前端用「需登录态」占位）
        接口异常 —— None
    """
    user_id = os.getenv('HAIJIAO_USER_ID', '')
    user_token = os.getenv('HAIJIAO_USER_TOKEN', '')
    if not (user_id and user_token):
        logger.warning('HAIJIAO_USER_ID / HAIJIAO_USER_TOKEN 未配置，视频取不到')
        return None
    try:
        resp = requests.get(
            f'{API_BASE}{LINE_PATH}/video/m3u8',
            params={
                'topic_id': topic_id,
                'attachment_id': attachment_id,
                'user_id': user_id,
                'user_token': user_token,
            },
            timeout=VIDEO_TIMEOUT,
            headers={'User-Agent': USER_AGENT},
        )
    except Exception:
        logger.exception('小影海角视频接口请求失败: %s/%s', topic_id, attachment_id)
        return None
    if not resp.ok or 'application/vnd.apple.mpegurl' not in resp.headers.get('Content-Type', ''):
        logger.warning('小影海角视频接口异常: status=%s ct=%s',
                       resp.status_code, resp.headers.get('Content-Type'))
        return None
    return resp.text


# ============================================================
# 其它站点级数据（公开只读）
# ============================================================


def get_gifts(kind='gold', page=1):
    """打赏礼物清单（金币 / 钻石两套），站点级公共数据、无需登录"""
    if kind not in ('gold', 'diamond'):
        kind = 'gold'
    return _cached_data(
        f'{CACHE_PREFIX}:gifts:{kind}:{page}',
        settings.XIAOYING_MOVIE_CACHE_TTL,
        f'{LINE_PATH}/gift/list',
        {'kind': kind, 'page': page},
    )


# ============================================================
# 账号：注册 / 登录（公开接口，不需要登录态）
# ============================================================
# 说明：这些接口直接作用在源站账号上 —— register 会在源站**真实创建账号**，
# 所以只在本站访客主动提交时调用，不做任何自动化批量调用。


def _public_post(path, params=None, timeout=AUTH_TIMEOUT):
    """公开 POST：返回 (data, msg)，data 为 None 表示失败

    失败时把接口给的 msg 透出去（如「验证码错误」「用户名已存在」），
    视图层要原样展示给访客，不然用户不知道错在哪。
    """
    try:
        body = signed_post(path, params, timeout=timeout)
    except Exception:
        logger.exception('小影海角接口请求失败: %s', path)
        return None, '网络异常，请稍后重试'
    if body.get('code') == SUCCESS_CODE and body.get('data') is not None:
        return clean_payload(body.get('data')), body.get('msg') or '成功'
    msg = body.get('msg') or f'接口返回异常（code={body.get("code")}）'
    logger.warning('小影海角接口返回异常: %s code=%s msg=%s', path, body.get('code'), msg)
    return None, msg


def get_register_captcha(use_proxy=False):
    """取注册图形验证码：返回 (data, msg)

    data = captcha_token（提交注册时回传）/ captcha_image（data URI，可直接给 <img>）/
    expires_in（有效期秒，实测 600）。
    源站注册必须填图形验证码且当前只能人工识别，所以本站把图直接展示给访客。
    """
    return _public_post(f'{LINE_PATH}/register/captcha',
                        {'use_proxy': 'true' if use_proxy else 'false'})


def get_register_credentials():
    """生成一组注册凭据：返回 (data, msg)，data = username / password / email

    只生成、不注册。用户名统一 xy_ 前缀共 12 位，符合源站长度上限。
    """
    return _public_post(f'{LINE_PATH}/register/credentials')


def register(captcha_token, captcha_code, username, password, email):
    """提交注册：返回 (data, msg)，data = user_id / username / nickname / email / token

    ⚠️ 会在海角源站**真实创建账号**（接口文档原文：「请合规使用」）。
    验证码一次性，无论成败该 captcha_token 都立即作废。
    """
    return _public_post(f'{LINE_PATH}/register', {
        'captcha_token': captcha_token,
        'captcha_code': captcha_code,
        'username': username,
        'password': password,
        'email': email,
    })


def login(username, password):
    """账号登录：返回 (data, msg)，data = token / user_id / username / nickname / email

    正常风控下不需要图形验证码；密码错误等业务失败会在 msg 里说明。
    """
    return _public_post(f'{LINE_PATH}/login', {
        'username': username,
        'password': password,
    })


# ============================================================
# 需要登录态的接口
# ============================================================
# 一律直传 user_id + user_token（不用库内 account_id）：本站只在自己的会话里
# 保存登录态，不依赖对方的账号表，登录/登出边界更清楚。
# **全部不走缓存**：这些数据只对本人有意义，缓存键无法区分用户，一旦命中别人的
# 结果就是串号事故。


def _read(path, user_id, token, params=None, timeout=AUTH_TIMEOUT):
    """带登录态取数：返回 data 或 None（失败原因只进日志，不回显给访客）"""
    payload = dict(params or {})
    payload['user_id'] = user_id
    payload['user_token'] = token
    code, data, msg = _fetch_raw(path, payload, timeout=timeout)
    if code == SUCCESS_CODE and data is not None:
        return clean_payload(data)
    logger.warning('小影海角接口返回异常(带登录态): %s code=%s msg=%s', path, code, msg)
    return None


def _write(path, user_id, token, params=None, method='POST', timeout=AUTH_TIMEOUT):
    """带登录态的写操作：返回 (data, msg)

    写操作必须把源站给的原因带回去（金币不足 / 已关注 / 请勿灌水 …），
    不然访客只看到一个"失败"。
    """
    payload = dict(params or {})
    payload['user_id'] = user_id
    payload['user_token'] = token
    try:
        if method == 'GET':
            body = signed_get(path, payload, timeout=timeout)
        else:
            body = signed_post(path, payload, timeout=timeout)
    except Exception:
        logger.exception('小影海角写接口请求失败: %s', path)
        return None, '网络异常，请稍后重试'
    if body.get('code') == SUCCESS_CODE:
        data = body.get('data')
        return (clean_payload(data) if data is not None else {}), body.get('msg') or '成功'
    msg = body.get('msg') or f'接口返回异常（code={body.get("code")}）'
    logger.warning('小影海角写接口返回异常: %s code=%s msg=%s', path, body.get('code'), msg)
    return None, msg


def get_user_info(user_id, token, target_user_id):
    """用户主页资料（查别人也可以，只是 is_followed 需要登录态才准）

    返回 nickname / avatar / avatar_encrypted / description / fans_count /
    vip / famous / certified / is_followed / topic_count / video_count /
    comment_count / favorite_count / like_count。
    """
    return _read(f'{LINE_PATH}/user/info', user_id, token, {'target_user_id': target_user_id})


def get_wealth(user_id, token):
    """账号余额：gold（金币）/ diamond（钻石）"""
    return _read(f'{LINE_PATH}/user/wealth', user_id, token)


def get_wealth_log(user_id, token, kind='gold', page=1):
    """金币 / 钻石流水（分页，最新在前）"""
    return _read(f'{LINE_PATH}/user/wealth/log', user_id, token,
                 {'kind': kind if kind in ('gold', 'diamond') else 'gold', 'page': page})


def get_my_topics(user_id, token, status='published', page=1):
    """我的帖子：status = published（审核通过）/ pending（审核中）/ rejected（审核失败）"""
    if status not in ('published', 'pending', 'rejected'):
        status = 'published'
    return _read(f'{LINE_PATH}/topic/mine', user_id, token, {'status': status, 'page': page})


def get_liked_topics(user_id, token, page=1):
    """我点赞过的帖子（分页）"""
    return _read(f'{LINE_PATH}/topic/liked', user_id, token, {'page': page})


def get_favorite_folders(user_id, token):
    """我的收藏夹：{total, results:[{folder_id, name, count}]}

    count 是源站给的该夹帖子数；一个收藏都没有时 results 是空数组。
    """
    return _read(f'{LINE_PATH}/favorite/folders', user_id, token)


def get_favorite_topics(user_id, token, page=1, folder_id=0):
    """我收藏的帖子（分页，源站每页 20 条）

    :param folder_id: 收藏夹 ID，取自「我的收藏夹」；传 0（默认）表示**全部收藏**
                      （跨所有收藏夹）—— 这是源站的语义，不是"没筛选到"的占位值。
    """
    return _read(f'{LINE_PATH}/favorite/topics', user_id, token,
                 {'page': page, 'folder_id': folder_id})


def add_favorite(user_id, token, topic_id, folder_id=0):
    """收藏帖子

    ⚠️ folder_id 的语义与「我收藏的帖子」**不同**：这里缺省或 0 = 默认收藏夹
    （一个具体的夹）；而 favorite/topics 里 0 = 全部收藏（跨所有夹）。
    重复收藏是安全的（源站仍回成功，不必先查再收）。
    """
    return _write(f'{LINE_PATH}/favorite/add', user_id, token,
                  {'topic_id': topic_id, 'folder_id': folder_id})


def delete_favorite(user_id, token, topic_id):
    """取消收藏帖子；取消一篇本来就没收藏的，源站会拒绝（EXTERNAL_API_FAILED）"""
    return _write(f'{LINE_PATH}/favorite/delete', user_id, token, {'topic_id': topic_id})


def add_favorite_folder(user_id, token, folder_name):
    """新建收藏夹（源站限制：名称 1-12 位字符、不可重名）

    注意源站的取名缺陷：夹子被删/改名后旧名字不会释放，同名新建会报「已存在!」。
    """
    return _write(f'{LINE_PATH}/favorite/folder/add', user_id, token,
                  {'folder_name': folder_name})


def rename_favorite_folder(user_id, token, folder_id, folder_name):
    """重命名收藏夹：只改名字，夹内帖子不受影响

    源站返回里那个对象 id 恒为 0，不能用；成功与否只看 code。
    """
    return _write(f'{LINE_PATH}/favorite/folder/rename', user_id, token,
                  {'folder_id': folder_id, 'folder_name': folder_name})


def delete_favorite_folder(user_id, token, folder_id):
    """删除收藏夹；源站要求夹内为空，非空会拒绝（EXTERNAL_API_FAILED）"""
    return _write(f'{LINE_PATH}/favorite/folder/delete', user_id, token,
                  {'folder_id': folder_id})


def get_following(user_id, token):
    """我关注的人（源站一次全给，不分页）"""
    return _read(f'{LINE_PATH}/user/following', user_id, token)


def get_fans(user_id, token, page=1):
    """我的粉丝（分页）"""
    return _read(f'{LINE_PATH}/user/fans', user_id, token, {'page': page})


def sign_in(user_id, token):
    """每日签到：data.state = signed（成功，含 amount）/ already（今天已签）/ closed（未开放）"""
    return _write(f'{LINE_PATH}/sign-in', user_id, token)


def like_topic(user_id, token, topic_id, action='like'):
    """点赞 / 取消点赞：action = like / unlike；data.liked 为操作后的状态"""
    return _write(f'{LINE_PATH}/topic/like', user_id, token,
                  {'topic_id': topic_id, 'action': 'unlike' if action == 'unlike' else 'like'})


def get_like_state(user_id, token, topic_id):
    """我有没有赞过这个帖子：data.liked（帖子详情页用它决定按钮状态）"""
    return _read(f'{LINE_PATH}/topic/like/state', user_id, token, {'topic_id': topic_id})


def follow_user(user_id, token, target_user_id, action='follow'):
    """关注 / 取消关注用户（注意：源站这条是 GET）"""
    return _write(f'{LINE_PATH}/user/follow', user_id, token,
                  {'target_user_id': target_user_id,
                   'action': 'unfollow' if action == 'unfollow' else 'follow'},
                  method='GET')


def give_gift(user_id, token, topic_id, item_id=None, quantity=1, kind='gold'):
    """给帖子打赏（真实扣费，同一帖子可重复打赏；源站这条是 GET）

    不传 item_id 时服务端自动选该类型里最便宜的礼物。
    """
    params = {'topic_id': topic_id,
              'quantity': quantity,
              'kind': 'diamond' if kind == 'diamond' else 'gold'}
    if item_id:
        params['item_id'] = item_id
    return _write(f'{LINE_PATH}/topic/give', user_id, token, params, method='GET')
