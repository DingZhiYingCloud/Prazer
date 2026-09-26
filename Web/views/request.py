# 项目视图
#
# 数据全部来自小影 API（API/apis/movie.py，带缓存），本站不落库。
# 统一降级策略：接口失败时渲染空数据页，绝不把异常抛给访客；
# 详情/播放在数据缺失时返回 404（地址不对，不是服务端故障）。
import json
import logging
import re
from urllib.parse import quote

from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.html import escape

from API.apis import movie
from Web.services import pager
from Web.views.pic import pic_url

logger = logging.getLogger(__name__)

# 分类列表页支持的排序方式（键为接口参数，值为展示文案）。
# 顺序即页面上的展示顺序；hits（按人气）此前因上游翻页异常隐藏过，现已确认修复。
ORDERS = {'time': '按时间', 'hits': '按人气', 'score': '按评分'}
# 列表页支持的可选参数（用于拼筛选链接时保留其它条件）
FILTER_KEYS = ('order', 'year', 'area', 'genre', 'lang')

# 源站把这些字段用 "/" 串起来，且结尾会多一个斜杠（如 "申奥/张艺凡/许渌洋/"），
# 直接显示就是一串斜杠。这些字段改成按名字切分、用小标签排版（见 detail.html）。
NAME_INFO_KEYS = ('导演', '编剧', '主演')
_NAME_SPLIT_RE = re.compile(r'[/、,，]+')


def _info_items(info):
    """把详情接口的 info 整理成模板友好的行：[{label, text, names}]

    names 非空时模板用标签渲染，否则按纯文本渲染。
    """
    rows = []
    for key, value in (info or {}).items():
        text = (value or '').strip().strip('/').strip()
        names = []
        if key in NAME_INFO_KEYS:
            names = [name for name in _NAME_SPLIT_RE.split(text) if name]
        rows.append({'label': key, 'text': text, 'names': names})
    return rows


def _category_name(type_id):
    """分类名（含子分类）：从分类接口的 main + sub 里找，取不到返回 None（模板会退回兜底文案）"""
    data = movie.get_categories() or {}
    for key in ('main', 'sub'):
        for item in data.get(key) or []:
            if str(item.get('id')) == str(type_id):
                return item.get('name')
    return None


def _filter_options(group):
    """接口给的筛选组 → {value: name} 映射（同时充当白名单）"""
    options = {}
    for item in (group or {}).get('options') or []:
        value = item.get('value')
        if value not in (None, ''):
            options[str(value)] = item.get('name') or str(value)
    return options


def _pick(value, options):
    """把 URL 上的筛选值收敛到接口给出的可选值里

    不这样做的话，任何人用 ?area=随便一个词 都能造出新的缓存键并回源一次 ——
    既会把缓存目录打爆，也等于替源站扛下大量无意义的请求。
    """
    value = (value or '').strip()
    return value if value in options else ''


def _build_filter_bar(type_id, filters, selected):
    """整理列表页筛选栏的数据：排序链接 + 各筛选组 + 「已选」文案

    选项与可选值全部来自筛选接口（地区/题材/语言/年份各分类都不同，还会随上新增加），
    只有排序是固定枚举（time/hits/score），所以照旧用本地文案。
    """
    base = f'/list/{type_id}.html'

    def href(key=None, value=''):
        params = dict(selected)
        if key:
            params[key] = value
        pairs = [(k, params[k]) for k in FILTER_KEYS if params.get(k)]
        return base + (f'?{"&".join(f"{k}={quote(v)}" for k, v in pairs)}' if pairs else '')

    order_links = [{'label': '默认', 'href': href('order', ''), 'active': not selected.get('order')}]
    order_links += [{'label': label, 'href': href('order', value), 'active': selected.get('order') == value}
                    for value, label in ORDERS.items()]

    groups = []
    active_labels = []

    # 子分类：它的 value 就是 type_id（子分类是独立列表页，不是同一页的筛选）
    sub_types = (filters or {}).get('sub_types') or []
    if sub_types:
        groups.append({
            'key': 'sub',
            'label': '子分类',
            'options': [{'label': item.get('name'), 'href': f'/list/{item.get("value")}.html',
                         'active': False} for item in sub_types],
        })

    for group in (filters or {}).get('groups') or []:
        key = group.get('key')
        # 排序单独一行渲染；不认识的组（接口以后新增的）一律忽略，避免页面出现莫名其妙的筛选行
        if key not in FILTER_KEYS or key == 'order':
            continue
        options = _filter_options(group)
        if not options:
            continue
        label = group.get('name') or key
        rows = [{'label': '全部', 'href': href(key, ''), 'active': not selected.get(key)}]
        rows += [{'label': name, 'href': href(key, value), 'active': selected.get(key) == value}
                 for value, name in options.items()]
        groups.append({'key': key, 'label': label, 'options': rows})
        if selected.get(key):
            active_labels.append(f'{label} {options.get(selected[key], selected[key])}')

    return order_links, groups, active_labels


def _movie_json_ld(request, data, vod_id):
    """详情页结构化数据（schema.org Movie），用于搜索引擎富摘要

    只输出确实有值的字段：宁可少写也不写错 —— 例如豆瓣 0.0 分这种没意义的评分、
    以及拿不到票数的 aggregateRating，一律不写（编造票数会被判为垃圾结构化数据）。
    """
    info = data.get('info') or {}
    ld = {
        '@context': 'https://schema.org',
        '@type': 'Movie',
        'name': data.get('name') or '',
        'url': request.build_absolute_uri(f'/detail/{vod_id}.html'),
    }
    if data.get('intro'):
        ld['description'] = data['intro']
    if data.get('cover'):
        ld['image'] = request.build_absolute_uri(pic_url(data['cover']))
    released = (info.get('上映') or '')[:10]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', released):
        ld['datePublished'] = released
    for key, field in (('导演', 'director'), ('主演', 'actor')):
        names = [name for name in _NAME_SPLIT_RE.split((info.get(key) or '').strip('/')) if name]
        if names:
            ld[field] = [{'@type': 'Person', 'name': name} for name in names[:10]]
    # 转义 "</"：结构化数据里若出现 </script> 会提前关闭脚本块（XSS）
    return json.dumps(ld, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


def index(request):
    """首页：轮播图 + 各推荐区块（一次接口拿全）

    区块里的「专题」条目（如 555独家专题）没有影片 id、url 指向源站专题页，本站无法承载，
    统一过滤掉；过滤后为空的区块不再渲染 —— 否则会生成 /detail/None.html 这类死链。
    """
    data = movie.get_home() or {}
    blocks = []
    for block in data.get('blocks') or []:
        items = [item for item in (block.get('items') or []) if item.get('id')]
        if items:
            blocks.append({'title': block.get('title'), 'items': items})
    return render(request, 'index.html', {
        'carousel': data.get('carousel') or [],
        'blocks': blocks,
    })


def movie_list(request, type_id, page=1):
    """分类列表页：分页 + 排序 + 地区/题材/语言/年份筛选（选项由筛选接口动态给出）

    type_id / page 由路由保证为整数。带筛选参数的页面在模板里设 noindex ——
    排序与各种筛选能组合出大量地址，全部放任收录会把同一个列表变成一堆重复内容页。

    筛选值一律先对着筛选接口返回的可选值做白名单收敛（见 _pick）：既是防脏参数，
    也避免有人拿随便造的 ?area=xxx 把缓存目录打爆。
    """
    page = max(1, page)
    # 第 1 页统一收敛到 /list/<type_id>.html，避免 /1.html 与无页码地址重复收录
    # （判断用「路径是否等于干净地址」而非 endswith，否则 /list/1.html 会重定向到自己）
    if page == 1 and request.path != f'/list/{type_id}.html':
        query = request.META.get('QUERY_STRING', '')
        return redirect(f'/list/{type_id}.html' + (f'?{query}' if query else ''), permanent=True)

    filters = movie.get_filters(type_id) or {}
    groups_by_key = {group.get('key'): group for group in (filters.get('groups') or [])}

    order = request.GET.get('order') or ''
    if order not in ORDERS:
        order = ''
    selected = {'order': order}
    for key in ('year', 'area', 'genre', 'lang'):
        selected[key] = _pick(request.GET.get(key), _filter_options(groups_by_key.get(key)))

    data = movie.get_list(
        type_id, page=page,
        order=selected['order'] or None, year=selected['year'] or None,
        area=selected['area'] or None, genre=selected['genre'] or None,
        lang=selected['lang'] or None,
    ) or {}
    meta = data.get('pagination') or {}
    try:
        total_pages = max(1, int(meta.get('total') or 1))
    except (TypeError, ValueError):
        total_pages = 1

    def page_url(target):
        """生成分页地址（保留当前的全部筛选条件）"""
        target = min(max(1, int(target)), total_pages)
        path = f'/list/{type_id}.html' if target == 1 else f'/list/{type_id}/{target}.html'
        pairs = [(key, selected[key]) for key in FILTER_KEYS if selected.get(key)]
        return path + (f'?{"&".join(f"{key}={quote(value)}" for key, value in pairs)}' if pairs else '')

    items = data.get('items') or []
    order_links, filter_groups, active_labels = _build_filter_bar(type_id, filters, selected)

    type_name = _category_name(type_id) or '影视分类'
    return render(request, 'list.html', {
        'type_id': type_id,
        'type_name': type_name,
        'page': page,
        'items': items,
        'total_pages': total_pages,
        'order_links': order_links,
        'filter_groups': filter_groups,
        'active_labels': active_labels,
        'pagination': {'links': pager.build(page, total_pages, page_url)},
        'filtered': any(selected.values()),
        'empty': not items,
        'breadcrumbs': [{'label': '首页', 'href': '/'}, {'label': type_name}],
    })


def detail(request, vod_id):
    """影片详情页：简介 / 元数据 / 播放源与选集（选集链接指向本站播放页）"""
    data = movie.get_detail(vod_id)
    if not data:
        return error_404(request)
    sources = data.get('sources') or []
    return render(request, 'detail.html', {
        'vod_id': vod_id,
        'detail': data,
        'sources': sources,
        'info_items': _info_items(data.get('info')),
        # 选集面板默认落在第一条线路（browse 模式，见 common_html/episode_picker.html）
        'current_sid': sources[0].get('sid') if sources else None,
        'breadcrumbs': [{'label': '首页', 'href': '/'}, {'label': data.get('name') or '影片详情'}],
        'movie_ld': _movie_json_ld(request, data, vod_id),
    })


def play(request, vod_id, sid, nid):
    """播放页：取指定播放源/集数的 m3u8，并列出该源的选集供切换

    m3u8 为源站直出地址（带时效，接口侧已做较短缓存），本站不做代理转发。
    """
    detail_data = movie.get_detail(vod_id) or {}
    play_data = movie.get_play(vod_id, sid, nid)
    if not detail_data or not play_data:
        return error_404(request)

    sources = detail_data.get('sources') or []
    current = next((s for s in sources if str(s.get('sid')) == str(sid)), None)
    return render(request, 'play.html', {
        'vod_id': vod_id,
        'name': detail_data.get('name'),
        'cover': detail_data.get('cover'),
        'm3u8': play_data.get('m3u8') or '',
        'sources': sources,
        'episodes': (current or {}).get('episodes') or [],
        'sid': sid,
        'nid': nid,
        'breadcrumbs': [
            {'label': '首页', 'href': '/'},
            {'label': detail_data.get('name') or '影片详情', 'href': f'/detail/{vod_id}.html'},
            {'label': '播放'},
        ],
    })


def search(request, keyword):
    """搜索页：按关键词搜影片（接口不分页，一次返回全部结果）

    空关键词（有人手敲 /so/%20%20.html 这类地址）直接退回首页，
    留着只会渲染出一个空壳页，对用户和搜索引擎都是垃圾页。
    """
    keyword = (keyword or '').strip()
    if not keyword:
        return redirect('home')
    data = movie.get_search(keyword) or {}
    return render(request, 'search.html', {
        'keyword': keyword,
        'results': data.get('results') or [],
        'breadcrumbs': [{'label': '首页', 'href': '/'}, {'label': '搜索'}],
    })


def error_404(request, exception=None):
    """404 错误页：访问不存在的路径或文件时返回（DEBUG=False 时生效）"""
    return render(request, '404.html', status=404)


def error_500(request, exception=None):
    """500 错误页：服务器内部错误时返回（DEBUG=False 时生效）"""
    return render(request, '500.html', status=500)


# ============ Sitemap（站点地图） ============
# 只放**当前确实可被收录**的页面（sitemap 里出现 noindex 页面是搜索引擎明确不建议的），
# 每一项的收录条件都与页面模板的 robots 判定保持同一份数据源：
#   首页            首页聚合两个区块任一非空才列（模板判的是 carousel/blocks）
#   分类列表页      分类接口返回的主分类（模板判的是 items，空数据页模板设 noindex）
#   影片详情页      首页与各分类第 1 页里出现的影片（这些页面确定有内容）
# 内容来自实时抓取，本地没有可信时间戳，因此不写 lastmod（宁缺勿假）。
# 生成的**路径**列表缓存 6 小时；绝对地址在每次响应时按当前请求域名拼，换域名不会留下死链。
SITEMAP_CACHE_KEY = 'xyapi:sitemap_urls'
SITEMAP_CACHE_TTL = 60 * 60 * 6  # 6 小时


def _build_sitemap_urls():
    """收集 sitemap 的 URL：(路径, changefreq, priority)"""
    urls = []
    seen = set()

    def add(path, freq, priority):
        if path and path not in seen:
            seen.add(path)
            urls.append((path, freq, priority))

    home = movie.get_home() or {}
    if (home.get('carousel') or []) or (home.get('blocks') or []):
        add('/', 'daily', '1.0')

    # 详情页来源：首页轮播 + 首页各区块 + 各分类第 1 页
    videos = list(home.get('carousel') or [])
    for block in home.get('blocks') or []:
        videos.extend(block.get('items') or [])

    categories = (movie.get_categories() or {}).get('main') or []
    for category in categories:
        type_id = category.get('id')
        add(f'/list/{type_id}.html', 'daily', '0.8')
        videos.extend(((movie.get_list(type_id, page=1) or {}).get('items')) or [])

    for video in videos:
        if video.get('id'):
            add(f'/detail/{video["id"]}.html', 'weekly', '0.6')
    return urls


def sitemap(request):
    """sitemap.xml：首页 + 分类页 + 详情页，路径列表缓存 6 小时

    单文件 sitemap 上限 5 万条 URL / 50 MB（未压缩），本站收录量远低于上限。
    """
    urls = cache.get(SITEMAP_CACHE_KEY)
    if urls is None:
        urls = _build_sitemap_urls()
        # 取数失败时 _build_sitemap_urls() 返回的是空列表，此时**不写缓存**：
        # 否则空站点地图会在整整一个 TTL（6 小时）内一直返回给搜索引擎。
        # 原则与 API/apis/movie.py 的 _cached 一致：只缓存成功的结果。
        if urls:
            cache.set(SITEMAP_CACHE_KEY, urls, SITEMAP_CACHE_TTL)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, freq, priority in urls:
        loc = escape(request.build_absolute_uri(path))
        lines.append(f'  <url><loc>{loc}</loc>'
                     f'<changefreq>{freq}</changefreq><priority>{priority}</priority></url>')
    lines.append('</urlset>')
    return HttpResponse('\n'.join(lines), content_type='application/xml')
