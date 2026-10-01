"""海角帖子 → 影片卡片结构（列表页 / 搜索页 / 个人中心的「我点赞的」共用）

common_html/movie_card.html 只认这几个键：id / name / cover / note / category，
所以这里把接口返回的帖子统一整理成这个形状，各页面不必各写一遍。

注意：接口的 tags 是 [{'id':…, 'name':…}] 而不是字符串数组，
直接丢给模板会渲染成一串 Python dict 原文，所以必须过 tag_names()。
"""
from Web.services import haijiao_media


def tag_names(item):
    """取标签名数组（接口给的是 dict 数组）"""
    names = []
    for tag in (item or {}).get('tags') or []:
        name = (tag or {}).get('name') if isinstance(tag, dict) else tag
        if name:
            names.append(name)
    return names


def _note(item, node_name):
    """卡片下方那一行说明：板块 + 阅读数 + 评论数"""
    parts = []
    if node_name:
        parts.append(node_name)
    view_count = item.get('view_count')
    if view_count:
        parts.append(f'{view_count} 阅读')
    comment_count = item.get('comment_count')
    if comment_count:
        parts.append(f'{comment_count} 评论')
    return ' · '.join(parts)


def _stats(item):
    """互动数据（图标 + 数字）

    只给个人中心的卡片用（movie_card 传 show_stats 时才渲染）：那边用图标版
    替代文字版 note，避免同一行信息重复。影视 / 短剧的卡片没有这个键，不受影响。
    """
    return [
        {'icon': 'eye', 'value': item.get('view_count') or 0},
        {'icon': 'heart', 'value': item.get('like_count') or 0},
        {'icon': 'comment', 'value': item.get('comment_count') or 0},
    ]


def cards(items):
    """帖子数组 → 卡片数组（无 topic_id 的条目直接跳过）"""
    result = []
    for item in items or []:
        topic_id = item.get('topic_id')
        if not topic_id:
            continue
        node_name = (item.get('node') or {}).get('name') or ''
        tags = tag_names(item)
        images = item.get('images') or []
        cover = haijiao_media.media_url(images[0]) if images else ''
        result.append({
            'id': topic_id,
            # 标题为空说明源站只回了骨架（少数接口如此），给个中性占位，
            # 否则卡片是一片空白，看着像页面坏了
            'name': item.get('title') or f'帖子 {topic_id}',
            # 没有配图时退到站点占位图：<img src=""> 在浏览器里是破图，
            # 而 common.js 的兜底只处理"加载失败"，不处理空地址
            'cover': cover or '/media/placeholder.png',
            'note': _note(item, node_name),
            'stats': _stats(item),
            'category': node_name or (tags[0] if tags else '海角社区'),
        })
    return result
