"""全站导航 context processor

职责：把分类接口的数据注入全站模板，一次取数供两处导航使用：
    nav_categories     主分类       —— 侧边栏「频道」与页脚「频道入口」
    nav_subcategories  连续剧子分类 —— 侧边栏「剧集专区」

数据来自小影电影分类接口（API/apis/movie.py 的 get_categories，返回 main / sub / labels 三段），
本身带 6 小时缓存，调用成本很低；接口异常时返回空列表，页面照常可访问（导航只剩首页）。

接口文档说明 sub 段的 id 可直接当「列表」接口的 type_id 用，所以每个子分类就是一张独立列表页。
labels 段（专题）没有对应的取内容接口，暂未使用。
"""
from API.apis import movie

# 主分类图标：小影接口只给 id / name，图标在本站按 id 映射（渲染见 common_html/nav_icon.html）。
# 新增分类时在这里补一行；没命中的走默认图标。
CATEGORY_ICONS = {
    1: 'film',       # 电影
    2: 'tv',         # 连续剧
    3: 'star',       # 综艺纪录
    4: 'sparkles',   # 动漫
    124: 'gift',     # 福利
    126: 'flame',    # 擦边短剧
}
DEFAULT_ICON = 'grid'


def nav_categories(request):
    """向全站模板注入导航分类数据（主分类 + 子分类，共用一次取数）"""
    data = movie.get_categories() or {}

    categories = []
    for item in data.get('main') or []:
        categories.append({
            'id': item.get('id'),
            'name': item.get('name'),
            'icon': CATEGORY_ICONS.get(item.get('id'), DEFAULT_ICON),
        })

    # 子分类不需要图标：接口没给能区分子分类的图标，5 项套同一个图标只是噪音，
    # 侧边栏里靠「剧集专区」小标题分层即可。
    subcategories = []
    for item in data.get('sub') or []:
        if item.get('id'):
            subcategories.append({
                'id': item.get('id'),
                'name': item.get('name'),
            })

    return {
        'nav_categories': categories,
        'nav_subcategories': subcategories,
    }
