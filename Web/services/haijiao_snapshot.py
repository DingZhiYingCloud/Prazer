"""列表页数据源：从本地快照里随机抽取卡片

列表页（首页 / 各栏目）不再实时请求小影 API，而是读本地快照
（API.models.HaijiaoTopicSnapshot，用 `manage.py build_haijiao_snapshot` 生成）。

每次刷新都**重新随机抽取**一屏，同一屏内不重复（不重不漏地打乱后按页切片）。
卡片结构与 haijiao_cards.cards() 一致，模板 common_html/movie_card.html 无需改动。

翻译：快照行里按语言存了译文（translations），有译文用译文、没有回退中文原文。
"""
import random

from django.utils.translation import get_language

from API.models import HaijiaoTopicSnapshot
from Web.services import haijiao_cards, haijiao_media

# 每页卡片数（与接口每页条数一致）
PER_PAGE = 20
PLACEHOLDER = '/media/placeholder.png'


def _localized(row, lang):
    """取按当前语言显示的三段文字：标题 / 板块 / 分类（无译文则回退中文原文）"""
    data = (row.translations or {}).get(lang) or {}
    return (
        data.get('title') or row.title,
        data.get('node') or row.node_name,
        data.get('category') or row.category,
    )


def random_page(page, per_page=PER_PAGE):
    """随机抽一屏：返回 {'items', 'total', 'total_pages'}

    page 会被收敛到 [1, total_pages]；快照为空时返回空列表（模板走空态）。
    """
    ids = list(HaijiaoTopicSnapshot.objects.values_list('id', flat=True))
    total = len(ids)
    if not total:
        return {'items': [], 'total': 0, 'total_pages': 1}

    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, int(page)), total_pages)

    random.shuffle(ids)
    chosen = ids[(page - 1) * per_page: page * per_page]
    rows = {row.id: row for row in HaijiaoTopicSnapshot.objects.filter(id__in=chosen)}

    lang = get_language()
    items = []
    for pk in chosen:
        row = rows.get(pk)
        if row is None:
            continue
        title, node_name, category = _localized(row, lang)
        items.append({
            'id': row.topic_id,
            'name': title or f'帖子 {row.topic_id}',
            'cover': haijiao_media.media_url(row.cover) or PLACEHOLDER,
            'note': haijiao_cards.build_note(node_name, row.view_count, row.comment_count),
            'stats': [
                {'icon': 'eye', 'value': row.view_count or 0},
                {'icon': 'heart', 'value': row.like_count or 0},
                {'icon': 'comment', 'value': row.comment_count or 0},
            ],
            'category': category,
        })
    return {'items': items, 'total': total, 'total_pages': total_pages}
