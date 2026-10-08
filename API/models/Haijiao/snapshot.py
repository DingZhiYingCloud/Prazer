"""海角社区帖子快照（列表页的数据源）

列表页不再实时请求小影 API，而是用一份**本地快照**：先用
`python manage.py build_haijiao_snapshot` 抓「热帖」前 N 页存到这里，
页面每次刷新从快照里**随机抽取**一屏展示（见 Web/services/haijiao_snapshot.py）。

只存列表卡片需要的字段 —— 详情页已锁"App 内观看"，正文 / 播放地址都不在本站展示，
所以没必要存。cover 存**源站原始地址**，渲染时再经 haijiao_media 处理
（这样将来换图片端点也不会留下写死的旧地址）。

translations 按语言存译文：{'pt-br': {'title': …, 'node': …, 'category': …}}。
没配翻译服务时它是空的，渲染时自动回退中文原文字段。
"""
from django.db import models

from API.common.base import BaseModel


class HaijiaoTopicSnapshot(BaseModel):
    """一条海角帖子（列表展示用）"""

    topic_id = models.CharField('帖子 ID', max_length=32, unique=True)
    title = models.CharField('标题', max_length=255)
    node_name = models.CharField('板块', max_length=64, blank=True, default='')
    category = models.CharField('分类（板块，无板块时取首个标签）', max_length=64, blank=True, default='')
    cover = models.CharField('封面（源站原始地址）', max_length=512, blank=True, default='')
    view_count = models.PositiveIntegerField('阅读数', default=0)
    like_count = models.PositiveIntegerField('点赞数', default=0)
    comment_count = models.PositiveIntegerField('评论数', default=0)
    source_page = models.PositiveIntegerField('来源页码', default=0)
    translations = models.JSONField('各语言译文', default=dict, blank=True)

    class Meta:
        verbose_name = '海角帖子快照'
        verbose_name_plural = '海角帖子快照'
        db_table = 'haijiao_topic_snapshot'
        ordering = ['-id']

    def __str__(self):
        return f'{self.topic_id} {self.title[:20]}'
