"""海角社区账号视图：注册 / 登录 / 登出 / 个人中心

只服务 /haijiao/ 频道（登录态见 Web/services/haijiao_auth.py），
站内其它频道没有登录概念，完全不受影响。

URL 形态：
    /haijiao/register.html              注册（随机凭据 + 图形验证码）
    /haijiao/login.html                 登录
    /haijiao/logout.html                退出登录
    /haijiao/me.html                    个人中心（资料 + 余额）
    /haijiao/me/topics.html             我的帖子（?status=published|pending|rejected）
    /haijiao/me/liked.html              我点赞过的帖子
    /haijiao/me/favorites.html          我的收藏（?folder_id= 选夹，缺省/0 = 全部）
    /haijiao/me/following.html          我关注的人
    /haijiao/me/fans.html               我的粉丝
    /haijiao/me/wealth.html             金币 / 钻石流水（?kind=gold|diamond）

关于注册：按「随机凭据」方案走 —— 访客只需认图填验证码，用户名 / 密码 / 邮箱由
小影 API 生成（用户名统一 xy_ 前缀）。凭据会在页面上展示，本站**不保存密码**，
提交完即丢；注册成功后直接登录。注意海角源站会真实建号（接口文档原文：「请合规使用」）。
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from django.shortcuts import redirect, render

from API.apis import haijiao
from Web.services import haijiao_auth, haijiao_cards, haijiao_media, pager

logger = logging.getLogger(__name__)

# 我的帖子三个审核状态（与源站「我的帖子」页的三个 tab 一致）
TOPIC_STATUSES = (
    ('published', '审核通过'),
    ('pending', '审核中'),
    ('rejected', '未通过'),
)
# 审核状态的图标（模板里按状态取，配色类写在模板内 —— Tailwind 只扫模板，扫描不到 .py 里的类名）
STATUS_ICONS = {'published': 'check', 'pending': 'clock', 'rejected': 'x-circle'}
# 流水两种货币
WEALTH_KINDS = (('gold', '金币'), ('diamond', '钻石'))

# 补详情时的并发数：源站只给骨架的接口（我点赞的 / 我的帖子）要按 topic_id 逐个补，
# 串行 20 条会把页面拖到好几秒；详情本身有 6 小时缓存，同一条帖子不会反复回源。
DETAIL_WORKERS = 6
# 可以从帖子详情里补的字段（只在本地字段为空时补，不覆盖源站给的）
DETAIL_FIELDS = ('title', 'node', 'images', 'create_time', 'author', 'view_count',
                 'like_count', 'comment_count')


def _with_details(items):
    """给"只有骨架"的帖子条目补上帖子详情里的字段

    实测 /api/haijiao/topic/liked 返回的条目只有 topic_id 与阅读数，
    title / node / images / create_time 全是空的（文档说"字段与内容列表一致"，实际不是）。
    缺失的条目按 topic_id 补一次详情；拿不到就保持原样，页面照常渲染（标题给中性占位）。
    """
    rows = items or []
    targets = [str(row.get('topic_id')) for row in rows
               if row.get('topic_id') and not row.get('title')]
    if not targets:
        return rows

    fetched = {}
    try:
        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            for topic_id, detail in zip(targets, pool.map(haijiao.get_topic_detail, targets)):
                if detail:
                    fetched[topic_id] = detail
    except Exception:
        # 补详情只是锦上添花，失败不该让整页挂掉
        logger.exception('海角帖子补详情失败')

    merged = []
    for row in rows:
        detail = fetched.get(str(row.get('topic_id'))) or {}
        item = dict(row)
        for key in DETAIL_FIELDS:
            if not item.get(key) and detail.get(key):
                item[key] = detail[key]
        merged.append(item)
    return merged


def _breadcrumbs(*trail):
    """个人中心统一的导航层级：首页 / 海角社区 / 个人中心 / …"""
    items = [
        {'label': '首页', 'href': '/'},
        {'label': '海角社区', 'href': '/haijiao/list.html'},
    ]
    items += [{'label': label, 'href': href} if href else {'label': label}
              for label, href in trail]
    return items


def _me_context(request, active):
    """个人中心各页共用的上下文：账号 + 侧边导航的当前项"""
    return {
        'account': request.hj_account,
        'account_info': None,
        'me_nav': active,
        'me_links': [
            {'key': 'home', 'label': '个人中心', 'icon': 'user', 'href': '/haijiao/me.html'},
            {'key': 'topics', 'label': '我的帖子', 'icon': 'file', 'href': '/haijiao/me/topics.html'},
            {'key': 'liked', 'label': '我点赞的', 'icon': 'heart', 'href': '/haijiao/me/liked.html'},
            {'key': 'favorites', 'label': '我的收藏', 'icon': 'bookmark', 'href': '/haijiao/me/favorites.html'},
            {'key': 'following', 'label': '我关注的人', 'icon': 'user-plus', 'href': '/haijiao/me/following.html'},
            {'key': 'fans', 'label': '我的粉丝', 'icon': 'users', 'href': '/haijiao/me/fans.html'},
            {'key': 'wealth', 'label': '金币流水', 'icon': 'chart', 'href': '/haijiao/me/wealth.html'},
        ],
    }


def _user_card(item):
    """用户名片（关注 / 粉丝列表用）"""
    return {
        'user_id': item.get('user_id'),
        'nickname': item.get('nickname') or '',
        'avatar': haijiao_media.avatar_url(item),
        'description': item.get('description') or '',
        'fans_count': item.get('fans_count') or 0,
    }


# ============ 注册 / 登录 / 登出 ============


def haijiao_register(request):
    """注册：随机凭据 + 图形验证码（两步式，验证码由访客人工识别）

    GET  取一张验证码 + 一组随机凭据，展示在表单里（访客只需填验证码）
    POST 提交注册；成功后直接登录，并把凭据一次性展示出来让访客保存
    """
    if haijiao_auth.current(request) is not None:
        return redirect('/haijiao/me.html')

    # 注册成功后的回显（凭据只在这一步短暂存在会话里，渲染完立即删除）
    if request.GET.get('done') == '1':
        creds = request.session.pop('hj_new_creds', None)
        if not creds:
            return redirect('/haijiao/me.html')
        return render(request, 'haijiao_register.html', {
            'done': True,
            'creds': creds,
            'breadcrumbs': _breadcrumbs(('注册', None)),
        })

    error = ''
    captcha = {}
    creds = {}
    if request.method == 'POST':
        captcha_code = (request.POST.get('captcha_code') or '').strip()
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        email = (request.POST.get('email') or '').strip()
        if not captcha_code:
            error = '请填写图片里的验证码'
            creds = {'username': username, 'password': password, 'email': email}
        elif not (username and password and email):
            error = '账号凭据缺失，请点「换一组账号」后重试'
        else:
            data, msg = haijiao.register(
                request.POST.get('captcha_token') or '', captcha_code, username, password, email)
            if data:
                haijiao_auth.login_session(request, data)
                # 一次性回显凭据：本站不留密码，只有这一步能让访客把密码抄下来
                request.session['hj_new_creds'] = {
                    'username': username, 'password': password, 'email': email,
                    'nickname': data.get('nickname') or '',
                }
                return redirect('/haijiao/register.html?done=1')
            error = msg or '注册失败，请重试'
            # 验证码一次性：无论成败都作废，失败后必须换一张新的
            creds = {'username': username, 'password': password, 'email': email}

    if not creds:
        # 首次进入：取验证码 + 生成一组随机凭据
        creds, creds_msg = haijiao.get_register_credentials()
        creds = creds or {}
        if not creds:
            error = error or creds_msg

    captcha, captcha_msg = haijiao.get_register_captcha()
    if not captcha:
        error = error or captcha_msg

    return render(request, 'haijiao_register.html', {
        'done': False,
        'error': error,
        'captcha': captcha,
        'creds': creds,
        'breadcrumbs': _breadcrumbs(('注册', None)),
    })


def haijiao_login(request):
    """登录：用户名 + 密码（海角源站账号）

    正常风控下不需要验证码；登录成功后把 user_id + token 存进本站会话。
    失败原因（密码错误 / 账号不存在）原样展示，否则访客不知道错在哪。
    """
    next_url = haijiao_auth.safe_next(request)
    if haijiao_auth.current(request) is not None:
        return redirect(next_url)

    error = ''
    username = ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        if not (username and password):
            error = '请填写用户名和密码'
        else:
            data, msg = haijiao.login(username, password)
            if data:
                haijiao_auth.login_session(request, data)
                return redirect(next_url)
            error = msg or '登录失败，请检查用户名和密码'

    return render(request, 'haijiao_login.html', {
        'error': error,
        'username': username,
        'next': next_url,
        'breadcrumbs': _breadcrumbs(('登录', None)),
    })


def haijiao_logout(request):
    """退出登录：只清掉本会话里的海角账号，站点其它功能不受影响"""
    haijiao_auth.logout(request)
    return redirect('/haijiao/list.html')


# ============ 个人中心 ============


@haijiao_auth.login_required
def haijiao_me(request):
    """个人中心首页：资料 + 金币 / 钻石余额（外加签到入口）"""
    account = request.hj_account
    info = haijiao.get_user_info(account['user_id'], account['token'], account['user_id'])
    wealth = haijiao.get_wealth(account['user_id'], account['token'])
    context = _me_context(request, 'home')
    context.update({
        # 资料与余额都拿不到，基本就是登录态失效（token 过期 / 账号异常），
        # 这时不自动清会话（可能只是接口抖了一下），给访客一个重新登录的入口即可
        'expired': info is None and wealth is None,
        'info': {**info, 'avatar': haijiao_media.avatar_url(info)} if info else None,
        'wealth': wealth or {},
        'breadcrumbs': _breadcrumbs(('个人中心', None)),
    })
    return render(request, 'haijiao_me.html', context)


@haijiao_auth.login_required
def haijiao_me_topics(request):
    """我的帖子：按审核状态分 tab（审核通过 / 审核中 / 未通过），每页 10 条"""
    account = request.hj_account
    status = request.GET.get('status') or 'published'
    if status not in dict(TOPIC_STATUSES):
        status = 'published'
    page = pager.positive_int(request.GET.get('page'))
    data = haijiao.get_my_topics(account['user_id'], account['token'], status, page) or {}
    meta = data.get('pagination') or {}
    total_pages = pager.positive_int(meta.get('total_page'), default=page)

    rows = []
    for item in _with_details(data.get('results')):
        rows.append({
            'topic_id': item.get('topic_id') or '',
            'title': item.get('title') or '（无标题）',
            'node': (item.get('node') or {}).get('name') or '',
            'create_time': item.get('create_time') or '',
            'view_count': item.get('view_count') or 0,
            'like_count': item.get('like_count') or 0,
            'comment_count': item.get('comment_count') or 0,
            # 审核失败的条目没有 topic_id，源站给的原因在 remarks 里
            'remarks': item.get('remarks') or '',
            'status': status,
        })

    def page_url(target):
        target = min(max(1, int(target)), total_pages)
        return f'/haijiao/me/topics.html?status={status}' + ('' if target == 1 else f'&page={target}')

    context = _me_context(request, 'topics')
    context.update({
        'status': status,
        'status_label': dict(TOPIC_STATUSES)[status],
        'status_icon': STATUS_ICONS[status],
        'status_links': [{'slug': slug, 'label': label, 'active': slug == status,
                          'href': f'/haijiao/me/topics.html?status={slug}'}
                         for slug, label in TOPIC_STATUSES],
        'rows': rows,
        'page': page,
        'total_pages': total_pages,
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'breadcrumbs': _breadcrumbs(('个人中心', '/haijiao/me.html'), ('我的帖子', None)),
    })
    return render(request, 'haijiao_me_topics.html', context)


@haijiao_auth.login_required
def haijiao_me_liked(request):
    """我点赞过的帖子：卡片网格 + 分页（源站每页 20 条）"""
    account = request.hj_account
    page = pager.positive_int(request.GET.get('page'))
    data = haijiao.get_liked_topics(account['user_id'], account['token'], page) or {}
    items = haijiao_cards.cards(_with_details(data.get('results')))
    meta = data.get('pagination') or {}
    total_pages = pager.positive_int(meta.get('total_page'), default=page)

    def page_url(target):
        target = min(max(1, int(target)), total_pages)
        return '/haijiao/me/liked.html' + ('' if target == 1 else f'?page={target}')

    context = _me_context(request, 'liked')
    context.update({
        'items': items,
        'page': page,
        'total_pages': total_pages,
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'breadcrumbs': _breadcrumbs(('个人中心', '/haijiao/me.html'), ('我点赞的', None)),
    })
    return render(request, 'haijiao_me_liked.html', context)


@haijiao_auth.login_required
def haijiao_me_favorites(request):
    """我的收藏：收藏夹筛选 + 收藏的帖子（分页，源站每页 20 条）

    folder_id 缺省或为 0 = **全部收藏**（源站语义：跨所有收藏夹），
    不是"没选到夹"的占位值，所以默认不带参数也能拿到全部。
    非数字的 folder_id 一律按 0 处理（源站对非数字返回 PARAM_FORMAT_ERROR，
    这里直接在本地收敛，少一次注定失败的请求）。

    页面上的「取消收藏」「收藏夹增删改」是写操作，走 Web/views/haijiao_action.py，
    提交后跳回本页（POST-Redirect-GET）。
    """
    account = request.hj_account
    page = pager.positive_int(request.GET.get('page'))
    folder_id = (request.GET.get('folder_id') or '').strip()
    if not folder_id.isdigit():
        folder_id = '0'

    folders = haijiao.get_favorite_folders(account['user_id'], account['token']) or {}
    data = haijiao.get_favorite_topics(account['user_id'], account['token'], page, folder_id) or {}
    items = haijiao_cards.cards(_with_details(data.get('results')))
    meta = data.get('pagination') or {}
    total_pages = pager.positive_int(meta.get('total_page'), default=page)

    # 收藏夹筛选：第一个固定是「全部收藏」（不带 folder_id 参数，地址最干净）
    folder_links = [{'id': '0', 'name': '全部收藏', 'count': None,
                     'active': folder_id == '0', 'href': '/haijiao/me/favorites.html'}]
    for folder in folders.get('results') or []:
        fid = str(folder.get('folder_id'))
        folder_links.append({
            'id': fid,
            'name': folder.get('name') or f'收藏夹 {fid}',
            'count': folder.get('count'),
            'active': fid == folder_id,
            'href': f'/haijiao/me/favorites.html?folder_id={fid}',
        })

    def page_url(target):
        target = min(max(1, int(target)), total_pages)
        params = []
        if target > 1:
            params.append(f'page={target}')
        if folder_id != '0':
            params.append(f'folder_id={folder_id}')
        return '/haijiao/me/favorites.html' + (f'?{"&".join(params)}' if params else '')

    context = _me_context(request, 'favorites')
    context.update({
        'folder_id': folder_id,
        'folder_links': folder_links,
        # 重命名表单的默认值：当前选中的**具体**收藏夹（「全部收藏」是虚拟档，不给名字）
        'current_folder_name': next((link['name'] for link in folder_links
                                     if link['active'] and link['id'] != '0'), ''),
        'items': items,
        'total': meta.get('total') or 0,
        'page': page,
        'total_pages': total_pages,
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'breadcrumbs': _breadcrumbs(('个人中心', '/haijiao/me.html'), ('我的收藏', None)),
    })
    return render(request, 'haijiao_me_favorites.html', context)


@haijiao_auth.login_required
def haijiao_me_following(request):
    """我关注的人：源站一次全给、不翻页，所以没有分页器"""
    account = request.hj_account
    data = haijiao.get_following(account['user_id'], account['token']) or {}
    rows = [_user_card(item) for item in data.get('results') or []]
    context = _me_context(request, 'following')
    context.update({
        'rows': rows,
        'total': data.get('total') or len(rows),
        'breadcrumbs': _breadcrumbs(('个人中心', '/haijiao/me.html'), ('我关注的人', None)),
    })
    return render(request, 'haijiao_me_following.html', context)


@haijiao_auth.login_required
def haijiao_me_fans(request):
    """我的粉丝：分页（源站每页 20 条）"""
    account = request.hj_account
    page = pager.positive_int(request.GET.get('page'))
    data = haijiao.get_fans(account['user_id'], account['token'], page) or {}
    rows = [_user_card(item) for item in data.get('results') or []]
    meta = data.get('pagination') or {}
    total_pages = pager.positive_int(meta.get('total_page'), default=page)

    def page_url(target):
        target = min(max(1, int(target)), total_pages)
        return '/haijiao/me/fans.html' + ('' if target == 1 else f'?page={target}')

    context = _me_context(request, 'fans')
    context.update({
        'rows': rows,
        'page': page,
        'total_pages': total_pages,
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'breadcrumbs': _breadcrumbs(('个人中心', '/haijiao/me.html'), ('我的粉丝', None)),
    })
    return render(request, 'haijiao_me_fans.html', context)


@haijiao_auth.login_required
def haijiao_me_wealth(request):
    """金币 / 钻石流水：两种货币分 tab，每页 20 条"""
    account = request.hj_account
    kind = request.GET.get('kind') or 'gold'
    if kind not in dict(WEALTH_KINDS):
        kind = 'gold'
    page = pager.positive_int(request.GET.get('page'))
    data = haijiao.get_wealth_log(account['user_id'], account['token'], kind, page) or {}
    meta = data.get('pagination') or {}
    total_pages = pager.positive_int(meta.get('total_page'), default=page)

    rows = []
    for item in data.get('results') or []:
        amount = item.get('amount') or 0
        rows.append({
            'amount': amount,
            'income': amount >= 0,
            'balance_after': item.get('balance_after'),
            'time': item.get('time') or '',
            'description': item.get('description') or '',
        })

    def page_url(target):
        target = min(max(1, int(target)), total_pages)
        return f'/haijiao/me/wealth.html?kind={kind}' + ('' if target == 1 else f'&page={target}')

    context = _me_context(request, 'wealth')
    context.update({
        'kind': kind,
        'kind_links': [{'slug': slug, 'label': label, 'active': slug == kind,
                        'href': f'/haijiao/me/wealth.html?kind={slug}'}
                       for slug, label in WEALTH_KINDS],
        'rows': rows,
        'page': page,
        'total_pages': total_pages,
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'breadcrumbs': _breadcrumbs(('个人中心', '/haijiao/me.html'), ('金币流水', None)),
    })
    return render(request, 'haijiao_me_wealth.html', context)
