"""海角社区频道视图层（红果短剧之外又一条社区线路）

数据来自小影 API 的海角线路（见 API/apis/haijiao.py）。本站只读不写：
    列表（6 个栏目）→ 详情（含评论/视频附件）→ 视频播放

URL 形态：
    /haijiao/list.html                       首页（默认热帖 tab）
    /haijiao/list/<tab>.html                 某栏目第 1 页
    /haijiao/list/<tab>/<page>.html          某栏目第 N 页
    /haijiao/topic/<topic_id>.html           帖子详情
    /haijiao/play/<topic_id>/<aid>.html      视频播放源（m3u8 文本，喂给详情页的播放器）
    /haijiao/key/<token>                     m3u8 内联密钥字节（见 _rewrite_key_uri）
    /haijiao/search.html?key=xxx             关键词搜索

URL 收敛（避免同一内容出现两个地址）：
    /haijiao/list.html   ⇔ /haijiao/list/hot.html
    第 N 页（page=1）      ⇔ 不带页码的地址
"""
import base64
import logging
import re
from urllib.parse import quote

from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from API.apis import haijiao
from Web.services import haijiao_auth, haijiao_cards, haijiao_media, pager
from Web.views.request import error_404

logger = logging.getLogger(__name__)

# m3u8 里的密钥行：源站把 AES-128 的真密钥内联成 data: URI（见 _rewrite_key_uri）
# URI 取到引号为止 —— data: URI 自身含逗号（"base64,xxx"），不能按逗号截断
_KEY_URI_RE = re.compile(r'(#EXT-X-KEY:[^\r\n]*?URI=")([^"]+)(")', re.IGNORECASE)
_DATA_KEY_RE = re.compile(r'^data:[^,]*;base64,([A-Za-z0-9+/]+={0,2})$', re.IGNORECASE)


def _rewrite_key_uri(m3u8_text):
    """把 m3u8 里内联的 data: 密钥换成本站可取回的地址

    源站还原真密钥后把它内联成 URI="data:application/octet-stream;base64,xxx=="，
    但 hls.js（xgplayer 的 HLS 引擎）不认 data: URI 密钥，会把它当相对路径拼到
    m3u8 所在目录去请求，实测 404 —— 画面黑屏。所以转成 /haijiao/key/<token>：
    由本站把这个 base64 还原成密钥字节返回（见 haijiao_key）。

    只替换能识别的 base64 内联密钥；其它形态（外链密钥等）原样保留，别改坏 m3u8。
    """
    if not m3u8_text:
        return m3u8_text

    def replace(match):
        payload = _DATA_KEY_RE.match(match.group(2))
        if not payload:
            return match.group(0)
        token = payload.group(1).replace('+', '-').replace('/', '_')
        return f'{match.group(1)}{reverse("haijiao_key", args=[token])}{match.group(3)}'

    return _KEY_URI_RE.sub(replace, m3u8_text)


def _rank_items(results, limit=None):
    """排行榜条目 → 模板友好结构（头像解密 + 头衔名）"""
    rows = results or []
    if limit:
        rows = rows[:limit]
    items = []
    for row in rows:
        items.append({
            'rank': row.get('rank'),
            'user_id': row.get('user_id'),
            'nickname': row.get('nickname') or '',
            'avatar': haijiao_media.avatar_url(row),
            'value': row.get('value'),
            'vip': row.get('vip') or 0,
            'title': (row.get('title') or {}).get('name') or '',
        })
    return items


# 榜单数值的单位（表头用）
RANK_VALUE_LABELS = {'fans': '粉丝', 'liked': '获赞', 'wealth': '人气'}


def _rank_context(board, period, limit=None, base='/haijiao/ranking.html'):
    """排行榜上下文：榜单数据 + 3×3 切换链接（全站渲染，不依赖 JS）

    base 是"当前页地址"：首页底部与独立榜单页共用这套 tab，
    点 tab 只带 ?board=&period= 参数留在当前页。
    链接在视图层算好（模板不能给 callable 传参，与 drama_list 的 top_links 同款）。
    """
    if board not in haijiao.RANK_BOARDS:
        board = 'fans'
    if period not in haijiao.RANK_PERIODS:
        period = 'all'
    data = haijiao.get_ranking(board, period) or {}

    def switch_url(target_board, target_period, target_base=None):
        # 默认组合回落成不带参数的地址，避免"同一内容两个地址"
        target_base = target_base or base
        if target_board == 'fans' and target_period == 'all':
            return target_base
        return f'{target_base}?board={target_board}&period={target_period}'

    board_links = [{
        'slug': item,
        'label': haijiao.RANK_BOARD_LABELS[item],
        'href': switch_url(item, period),
        'active': item == board,
    } for item in haijiao.RANK_BOARDS]
    period_links = [{
        'slug': item,
        'label': haijiao.RANK_PERIOD_LABELS[item],
        'href': switch_url(board, item),
        'active': item == period,
    } for item in haijiao.RANK_PERIODS]

    return {
        'board': board,
        'period': period,
        'board_label': data.get('board_label') or haijiao.RANK_BOARD_LABELS[board],
        'period_label': data.get('period_label') or haijiao.RANK_PERIOD_LABELS[period],
        'total': data.get('total') or 0,
        'items': _rank_items(data.get('results'), limit),
        'value_label': RANK_VALUE_LABELS.get(board, '数值'),
        'board_links': board_links,
        'period_links': period_links,
        'full_href': switch_url(board, period, '/haijiao/ranking.html'),
        # 首页底部是"精简形态"（只有前 N 名 + 完整榜单入口）；独立榜单页是全量
        'compact': bool(limit),
    }


# ============ 视图 ============


def haijiao_index(request):
    """海角首页：等价于 /haijiao/list/hot.html 的第 1 页"""
    return haijiao_list(request, tab='hot', page=1)


def haijiao_list(request, tab, page=1):
    """海角列表：按栏目取内容列表（每页 20 条），带分页

    tab 必须是 6 个合法值之一（hot/news/events/original/essence/latest），
    否则 404 —— 海角接口对非法 tab 返回 PARAM_VALUE_INVALID，没必要专门
    渲染一个空壳页。
    """
    if tab not in haijiao.TABS:
        raise Http404(f'未知的海角栏目: {tab}')
    page = max(1, int(page))

    # 地址收敛：hot 第 1 页 = 首页地址；其他栏目第 1 页 = 不带页码；第 N 页带页码
    if tab == 'hot' and page == 1:
        canonical = '/haijiao/list.html'
    elif page == 1:
        canonical = f'/haijiao/list/{tab}.html'
    else:
        canonical = f'/haijiao/list/{tab}/{page}.html'
    if request.path != canonical:
        query = request.META.get('QUERY_STRING', '')
        return redirect(canonical + (f'?{query}' if query else ''), permanent=True)

    data = haijiao.get_topics(tab, page) or {}
    items = haijiao_cards.cards(data.get('results'))
    meta = data.get('pagination') or {}
    total_pages = pager.positive_int(meta.get('total_page') or meta.get('total'), default=page)
    type_name = f'{haijiao.TAB_LABELS.get(tab, tab)} · 海角社区'
    # tab 列表：[(slug, label), ...]，模板一次 for 拿到两个值最干净
    tab_options = [(t, haijiao.TAB_LABELS.get(t, t)) for t in haijiao.TABS]
    # 排行榜模块只出现在频道首页（热帖第 1 页）：维度/周期走 ?board=&period=，留在本页切换
    ranking = _rank_context(request.GET.get('board'), request.GET.get('period'),
                            limit=10, base='/haijiao/list.html') if tab == 'hot' and page == 1 else None

    def page_url(target):
        target = min(max(1, int(target)), total_pages)
        if tab == 'hot' and target == 1:
            return '/haijiao/list.html'
        if target == 1:
            return f'/haijiao/list/{tab}.html'
        return f'/haijiao/list/{tab}/{target}.html'

    return render(request, 'haijiao_list.html', {
        'tab': tab,
        'tab_options': tab_options,
        'type_name': type_name,
        'page': page,
        'total_pages': total_pages,
        'items': items,
        'ranking': ranking,
        'account': haijiao_auth.current(request),
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'empty': not items,
        'breadcrumbs': [
            {'label': '首页', 'href': '/'},
            {'label': '海角社区', 'href': '/haijiao/list.html'},
            {'label': haijiao.TAB_LABELS.get(tab, tab)},
        ],
    })


def haijiao_topic(request, topic_id):
    """帖子详情：标题 / 作者 / 正文 / 图片 / 视频附件 / 评论

    接口的 content 字段是源站正文 HTML（含混淆图片地址），本站直接渲染到模板。
    模板里把 <img src="混淆地址"> 替换为 /api/haijiao/image?url=... 的完整 URL。
    """
    data = haijiao.get_topic_detail(topic_id)
    if not data:
        return error_404(request)

    # 视频附件：补一份可直接给 <img> 用的封面地址（源站封面同样是 .txt 混淆地址）
    videos = [{**v, 'cover': haijiao_media.media_url(v.get('cover'))}
              for v in (data.get('videos') or [])]
    author = data.get('author') or {}
    content_html = haijiao_media.rewrite_content_images(data.get('content') or '')

    # 互动区（点赞 / 关注 / 打赏 / 收藏）：只有登录后才查这几项，未登录时页面给登录入口，
    # 免得每个访客都白搭几次接口调用。
    account = haijiao_auth.current(request)
    interactions = None
    if account is not None:
        author_id = str(author.get('id') or '')
        like_state = haijiao.get_like_state(account['user_id'], account['token'], topic_id) or {}
        author_card = (haijiao.get_user_info(account['user_id'], account['token'], author_id)
                       if author_id else None)
        gifts = (haijiao.get_gifts('gold') or {}).get('results') or []
        folders = (haijiao.get_favorite_folders(account['user_id'], account['token']) or {}).get('results') or []
        interactions = {
            'liked': bool(like_state.get('liked')),
            'author_user_id': author_id,
            'following': bool((author_card or {}).get('is_followed')),
            'is_self': author_id == account['user_id'],
            'gold': (haijiao.get_wealth(account['user_id'], account['token']) or {}).get('gold'),
            'gifts': [{'item_id': gift.get('item_id'),
                       'name': gift.get('name') or '',
                       'price': gift.get('sale_price') or 0}
                      for gift in gifts],
            # 收藏夹下拉：源站的「默认收藏夹」本身就在列表里（带真实 folder_id），
            # 一个夹都没有时才退到 folder_id=0 这个隐式默认夹。
            'favorite_folders': [{'folder_id': str(folder.get('folder_id')),
                                  'name': folder.get('name') or '未命名收藏夹'}
                                 for folder in folders if folder.get('folder_id')]
                                or [{'folder_id': '0', 'name': '默认收藏夹'}],
        }

    return render(request, 'haijiao_topic.html', {
        'topic_id': topic_id,
        'detail': data,
        'tags': haijiao_cards.tag_names(data),
        'videos': videos,
        'account': account,
        'interactions': interactions,
        'author': {
            **author,
            'avatar': haijiao_media.avatar_url(author),
        },
        'content': content_html,
        # 评论另起一个 AJAX/分页加载；首屏先塞前 20 条
        'comments': ((haijiao.get_comments(topic_id, 1) or {}).get('results')) or [],
        'breadcrumbs': [
            {'label': '首页', 'href': '/'},
            {'label': '海角社区', 'href': '/haijiao/list.html'},
            {'label': (data.get('title') or '帖子详情')[:40]},
        ],
    })


def haijiao_play(request, topic_id, attachment_id):
    """视频播放源：拉该附件的可播 m3u8（已还原真密钥），原样吐给播放器

    m3u8 文本不会写进模板（避免 HTML 转义破坏 EXT-X 行）；通过 view 直接
    吐 Content-Type: application/vnd.apple.mpegurl，前端 xgplayer + HLS 插件
    直接把它当 source（见 haijiao_topic.html 的 js 区块）。
    取不到时渲染兜底页并返回 404。
    """
    m3u8_text = haijiao.get_video_m3u8(topic_id, attachment_id)
    if not m3u8_text:
        return render(request, 'haijiao_play.html', {
            'topic_id': topic_id,
            'attachment_id': attachment_id,
            'ready': False,
            'error': '视频取不到：可能账号已失效，或该附件已被源站删除。',
            'breadcrumbs': [
                {'label': '首页', 'href': '/'},
                {'label': '海角社区', 'href': '/haijiao/list.html'},
                {'label': '视频播放'},
            ],
        }, status=404)
    return HttpResponse(
        _rewrite_key_uri(m3u8_text),
        content_type='application/vnd.apple.mpegurl',
    )


def haijiao_key(request, token):
    """m3u8 内联的 AES-128 密钥字节（配合 _rewrite_key_uri 使用）

    token 是密钥原始 base64 的 URL 安全变体（+ → -，/ → _），这里还原成字节返回。
    只接受 base64 字母表、且长度设上限：免得这个端点变成任意数据的中转站。
    """
    if len(token) > 128:
        raise Http404('密钥长度不合法')
    try:
        raw = base64.b64decode(token, altchars=b'-_', validate=True)
    except ValueError:
        raise Http404('密钥格式不合法')
    return HttpResponse(raw, content_type='application/octet-stream')


def haijiao_search(request):
    """关键词搜索：URL 用查询参数而非路径段（用户输入任意字符串，含斜杠会歧义）

    分页同样走查询参数 ?page=N：关键词是用户输入的任意串，做成路径段会出现
    「/haijiao/search/xxx/2.html」这种带斜杠就歧义的地址。
    """
    keyword = (request.GET.get('key') or '').strip()
    if not keyword:
        return redirect('/haijiao/list.html')
    page = pager.positive_int(request.GET.get('page'))
    data = haijiao.get_search(keyword, page) or {}
    items = haijiao_cards.cards(data.get('results'))
    meta = data.get('pagination') or {}
    total_pages = pager.positive_int(meta.get('total_page') or meta.get('total'), default=page)

    def page_url(target):
        target = min(max(1, int(target)), total_pages)
        qs = quote(keyword, safe='')
        return f'/haijiao/search.html?key={qs}' + ('' if target == 1 else f'&page={target}')

    return render(request, 'haijiao_search.html', {
        'keyword': keyword,
        'items': items,
        'account': haijiao_auth.current(request),
        'page': page,
        'total_pages': total_pages,
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'empty': not items,
        'breadcrumbs': [
            {'label': '首页', 'href': '/'},
            {'label': '海角社区', 'href': '/haijiao/list.html'},
            {'label': f'搜索「{keyword}」'},
        ],
    })


def haijiao_ranking(request):
    """完整排行榜：3 个维度 × 3 个周期，一次展示整张榜（源站不翻页，约 101 条）

    维度/周期走查询参数 ?board=&period=，非法值回落到默认（粉丝榜·总榜），
    和源站的 tab 语义一致；tab 切换是普通链接，不依赖 JS。
    """
    ranking = _rank_context(request.GET.get('board'), request.GET.get('period'),
                            base='/haijiao/ranking.html')
    return render(request, 'haijiao_ranking.html', {
        'ranking': ranking,
        'account': haijiao_auth.current(request),
        'breadcrumbs': [
            {'label': '首页', 'href': '/'},
            {'label': '海角社区', 'href': '/haijiao/list.html'},
            {'label': '排行榜'},
        ],
    })
