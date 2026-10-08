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
from django.utils.translation import get_language
from django.utils.translation import gettext as _

from API.apis import haijiao
from Web.services import (haijiao_auth, haijiao_cards, haijiao_media,
                          haijiao_snapshot, pager)
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


# ============ 视图 ============


def _list_canonical(tab, page):
    """栏目列表页的规范地址：hot 第 1 页 = 频道首页；其它栏目第 1 页不带页码；第 N 页带页码。

    一律用 reverse 生成，这样才能带上当前语言前缀（/pt-br/… 或 /zh-hans/…）。
    """
    if tab == 'hot' and page == 1:
        return reverse('haijiao_index')
    if page == 1:
        return reverse('haijiao_list', args=[tab])
    return reverse('haijiao_list_page', args=[tab, page])


def _render_list_page(request, tab, page, home=False):
    """渲染栏目列表（home=True 表示这是网站首页，分页第 1 页仍回首页）

    数据来自**本地快照**，不再实时请求小影 API：每次刷新从快照里随机抽一屏，
    各栏目共用一个池（见 Web/services/haijiao_snapshot.py）。
    """
    page = pager.positive_int(page)
    snapshot = haijiao_snapshot.random_page(page)
    items = snapshot['items']
    total_pages = snapshot['total_pages']
    page = min(page, total_pages)

    type_name = f'{haijiao.TAB_LABELS.get(tab, tab)} · {_("海角社区")}'
    # tab 列表：[(slug, label), ...]，模板一次 for 拿到两个值最干净
    tab_options = [(t, haijiao.TAB_LABELS.get(t, t)) for t in haijiao.TABS]
    base = reverse('home') if home else reverse('haijiao_index')

    def page_url(target):
        target = min(max(1, int(target)), total_pages)
        if target == 1:
            return base if home else _list_canonical(tab, 1)
        return reverse('haijiao_list_page', args=[tab, target])

    return render(request, 'haijiao_list.html', {
        'tab': tab,
        'tab_options': tab_options,
        'type_name': type_name,
        'page': page,
        'total_pages': total_pages,
        'items': items,
        'account': haijiao_auth.current(request),
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'empty': not items,
        'breadcrumbs': [
            {'label': _('首页'), 'href': reverse('home')},
            {'label': _('海角社区'), 'href': reverse('haijiao_index')},
            {'label': haijiao.TAB_LABELS.get(tab, tab)},
        ],
    })


def haijiao_home(request):
    """网站首页：直接渲染海角社区「热帖」第 1 页（内容等同频道首页）

    本站现在只保留海角社区一个频道，所以首页就是海角首页；
    非首页的别名（如 <语言前缀>/index/）统一收敛回首页。
    """
    home_url = reverse('home')
    if request.path != home_url:
        return redirect(home_url)
    return _render_list_page(request, tab='hot', page=1, home=True)


def haijiao_index(request):
    """海角社区列表首页（热帖第 1 页）：/haijiao/list.html"""
    return haijiao_list(request, tab='hot', page=1)


def haijiao_list(request, tab, page=1):
    """海角列表：按栏目取内容列表（每页 20 条），带分页

    tab 必须是 6 个合法值之一（hot/news/events/original/essence/latest），
    否则 404 —— 海角接口对非法 tab 返回 PARAM_VALUE_INVALID，没必要专门
    渲染一个空壳页。
    """
    if tab not in haijiao.TABS:
        raise Http404(_('未知的海角栏目: %(tab)s') % {'tab': tab})
    page = max(1, int(page))

    # 地址收敛：hot 第 1 页 = 首页地址；其他栏目第 1 页 = 不带页码；第 N 页带页码
    canonical = _list_canonical(tab, page)
    if request.path != canonical:
        query = request.META.get('QUERY_STRING', '')
        return redirect(canonical + (f'?{query}' if query else ''), permanent=True)

    return _render_list_page(request, tab, page)


def _locked_page(request, title, desc, crumb):
    """渲染「需在 App 内使用」的拦截页（帖子详情 / 搜索 / 登录 / 个人中心 共用）

    本站网页端只保留可静态化的内容（帖子列表）；其余功能引导去 App 内使用。
    """
    return render(request, 'haijiao_locked.html', {
        'locked_title': title,
        'locked_desc': desc,
        'breadcrumbs': [
            {'label': _('首页'), 'href': reverse('home')},
            {'label': crumb},
        ],
    })


def haijiao_topic(request, topic_id):
    """帖子详情：本站内容需在 App 内观看，详情正文不再对外展示

    直接访问（搜索、外链、收藏、手输地址）一律只给「下载 App」指引页；
    点卡片则是在当前页弹下载框、不跳转（见 common_html/app_download_modal.html）。
    完整的详情渲染逻辑保留在 _render_topic_detail()，恢复 App 内浏览时直接复用。
    """
    return _locked_page(
        request,
        _('内容需在 App 内观看'),
        _('本站内容已迁移到 App 内浏览，请下载安装后观看。'),
        _('内容需在 App 内观看'),
    )


def locked_search(request):
    """搜索：网页端不提供（要连小影接口、无法静态化），引导去 App 内使用"""
    return _locked_page(
        request, _('搜索'),
        _('搜索需在 App 内使用，请下载安装后在 App 内搜索。'),
        _('搜索'),
    )


def locked_login(request):
    """登录 / 注册：网页端不提供，引导去 App 内使用"""
    return _locked_page(
        request, _('登录'),
        _('登录需在 App 内使用，请下载安装后在 App 内登录。'),
        _('登录'),
    )


def locked_account(request):
    """个人中心：网页端不提供，引导去 App 内使用"""
    return _locked_page(
        request, _('个人中心'),
        _('个人中心需在 App 内使用，请下载安装后在 App 内查看。'),
        _('个人中心'),
    )


def _render_topic_detail(request, topic_id):
    """（暂未启用）完整的帖子详情渲染：标题 / 作者 / 正文 / 图片 / 视频附件 / 评论

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
            {'label': _('首页'), 'href': reverse('home')},
            {'label': _('海角社区'), 'href': reverse('haijiao_index')},
            {'label': (data.get('title') or _('帖子详情'))[:40]},
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
            'error': _('视频取不到：可能账号已失效，或该附件已被源站删除。'),
            'breadcrumbs': [
                {'label': _('首页'), 'href': reverse('home')},
                {'label': _('海角社区'), 'href': reverse('haijiao_index')},
                {'label': _('视频播放')},
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
        return redirect(reverse('haijiao_index'))
    page = pager.positive_int(request.GET.get('page'))
    data = haijiao.get_search(keyword, page) or {}
    items = haijiao_cards.cards(data.get('results'))
    meta = data.get('pagination') or {}
    total_pages = pager.positive_int(meta.get('total_page') or meta.get('total'), default=page)

    search_url = reverse('haijiao_search')

    def page_url(target):
        target = min(max(1, int(target)), total_pages)
        qs = quote(keyword, safe='')
        return f'{search_url}?key={qs}' + ('' if target == 1 else f'&page={target}')

    return render(request, 'haijiao_search.html', {
        'keyword': keyword,
        'items': items,
        'account': haijiao_auth.current(request),
        'page': page,
        'total_pages': total_pages,
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'empty': not items,
        'breadcrumbs': [
            {'label': _('首页'), 'href': reverse('home')},
            {'label': _('海角社区'), 'href': reverse('haijiao_index')},
            {'label': _('搜索「%(kw)s」') % {'kw': keyword}},
        ],
    })
