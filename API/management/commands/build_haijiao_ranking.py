"""抓取海角排行榜（3 维度 × 3 周期），写入本地快照

排行榜同样走"冻结"策略：页面直接读本地快照，不再实时请求小影接口。

用法：
    python manage.py build_haijiao_ranking
"""
from django.core.management.base import BaseCommand

from API.apis import haijiao
from API.models import HaijiaoRankingSnapshot


class Command(BaseCommand):
    help = '抓取海角排行榜（粉丝/点赞/人气 × 总/月/周）并写入快照表'

    def handle(self, *args, **options):
        saved = 0
        for board in haijiao.RANK_BOARDS:
            for period in haijiao.RANK_PERIODS:
                data = haijiao.get_ranking(board, period) or {}
                items = []
                for row in data.get('results') or []:
                    items.append({
                        'rank': row.get('rank'),
                        'user_id': row.get('user_id'),
                        'nickname': row.get('nickname') or '',
                        'avatar': row.get('avatar') or '',
                        'avatar_encrypted': row.get('avatar_encrypted'),
                        'value': row.get('value'),
                        'vip': row.get('vip') or 0,
                        'title': row.get('title') or {},
                    })
                HaijiaoRankingSnapshot.objects.update_or_create(
                    board=board,
                    period=period,
                    defaults={
                        'total': data.get('total') or len(items),
                        'items': items,
                    },
                )
                saved += 1
                self.stdout.write(f'{board}/{period} 完成（{len(items)} 条）')
        self.stdout.write(self.style.SUCCESS(f'排行榜快照完成：共 {saved} 张'))
