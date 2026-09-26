"""页头分类导航 context processor

职责：把电影主分类注入全站模板，供侧边栏导航与页脚使用。

数据来自小影电影分类接口（API/apis/movie.py 的 get_categories），本身带 6 小时缓存，
调用成本很低；接口异常时返回空列表，页面照常可访问（导航只剩首页）。
"""
from API.apis import movie

# 分类图标：小影接口只给 id / name，图标在本站按 id 映射（渲染见 common_html/nav_icon.html）。
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
    """向全站模板注入 nav_categories（形如 [{'id': 1, 'name': '电影', 'icon': 'film'}, ...]）"""
    data = movie.get_categories() or {}
    categories = []
    for item in data.get('main') or []:
        categories.append({
            'id': item.get('id'),
            'name': item.get('name'),
            'icon': CATEGORY_ICONS.get(item.get('id'), DEFAULT_ICON),
        })
    return {'nav_categories': categories}
