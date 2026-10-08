"""海角排行榜快照（排行榜页的数据源）

排行榜也能静态化（就是源站公开榜单，变化很慢），所以和帖子列表一样冻结到本地：
用 `python manage.py build_haijiao_ranking` 抓 3 维度 × 3 周期共 9 张榜存这里，
页面直接读库，不再实时请求小影接口。

items 存榜单条目数组，字段与接口返回一致（rank / user_id / nickname / avatar /
avatar_encrypted / value / vip / title），渲染时复用 Web/views/haijiao.py 的 _rank_items()。
维度与周期的展示名不存库：用 gettext 的词条在渲染时按当前语言取，避免把某种语言的
标签固化进数据库。
"""
from django.db import models

from API.common.base import BaseModel


class HaijiaoRankingSnapshot(BaseModel):
    """一张榜单（某维度 × 某周期）"""

    board = models.CharField('榜单维度', max_length=16)
    period = models.CharField('周期', max_length=16)
    total = models.PositiveIntegerField('总人数', default=0)
    items = models.JSONField('榜单条目', default=list, blank=True)

    class Meta:
        verbose_name = '海角排行榜快照'
        verbose_name_plural = '海角排行榜快照'
        db_table = 'haijiao_ranking_snapshot'
        unique_together = [('board', 'period')]
        ordering = ['board', 'period']

    def __str__(self):
        return f'{self.board}/{self.period}（{self.total} 人）'
