"""抓取海角「热帖」前 N 页，写入本地帖子快照（列表页的数据源）

列表页不再实时请求小影 API，改用这份快照 + 每次刷新随机抽取
（见 Web/services/haijiao_snapshot.py）。想更新快照时重跑本命令即可。

用法：
    python manage.py build_haijiao_snapshot                 # 默认抓「热帖」前 30 页
    python manage.py build_haijiao_snapshot --pages 30
    python manage.py build_haijiao_snapshot --tab latest    # 换栏目
    python manage.py build_haijiao_snapshot --translate     # 顺便翻成其它语言（需先配翻译服务）

说明：
    - 按 topic_id upsert，重复执行不会产生重复行；
    - 抓到的每一条都记下来源页码（source_page），便于排查；
    - --translate 需要 .env 里配好 TRANSLATE_PROVIDER / TRANSLATE_API_KEY，
      没配就跳过（快照保持中文，渲染时回退中文原文）。
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from API.apis import haijiao
from API.models import HaijiaoTopicSnapshot
from Web.services import translate as translate_service


class Command(BaseCommand):
    help = '抓取海角「热帖」前 N 页并写入帖子快照表'

    def add_arguments(self, parser):
        parser.add_argument('--pages', type=int, default=30, help='抓取页数，默认 30')
        parser.add_argument('--tab', default='hot', help='栏目，默认 hot（热帖）')
        parser.add_argument('--translate', action='store_true',
                            help='同时翻译为其它语言（用本地人工词表）')
        parser.add_argument('--translate-only', action='store_true',
                            help='不抓取，只按最新词表重刷一遍译文（补/改词表后用）')

    def handle(self, *args, **options):
        # 只重刷译文：补过 locale/<语言>/hardcoded.json 之后用它，不必重新抓接口
        if options['translate_only']:
            self._translate_all()
            return

        pages = max(1, options['pages'])
        tab = options['tab']

        saved = 0
        for page in range(1, pages + 1):
            data = haijiao.get_topics(tab, page) or {}
            results = data.get('results') or []
            if not results:
                self.stdout.write(f'第 {page} 页没有数据，停止（可能已到末页或被限流）')
                break
            for item in results:
                if self._save_item(item, page):
                    saved += 1
            self.stdout.write(f'第 {page} 页完成（累计写入 {saved} 条）')

        total = HaijiaoTopicSnapshot.objects.count()
        self.stdout.write(self.style.SUCCESS(f'快照写入完成：本次 {saved} 条，库内共 {total} 条'))

        if options['translate']:
            self._translate_all()

    def _save_item(self, item, page):
        """把一条接口结果 upsert 进快照；缺 topic_id 的条目跳过"""
        topic_id = str(item.get('topic_id') or '')
        if not topic_id:
            return False

        node_name = (item.get('node') or {}).get('name') or ''
        tags = [(tag or {}).get('name') for tag in (item.get('tags') or [])
                if isinstance(tag, dict)]
        tags = [name for name in tags if name]
        images = item.get('images') or []

        HaijiaoTopicSnapshot.objects.update_or_create(
            topic_id=topic_id,
            defaults={
                'title': item.get('title') or '',
                'node_name': node_name,
                'category': node_name or (tags[0] if tags else ''),
                'cover': images[0] if images else '',
                'view_count': item.get('view_count') or 0,
                'like_count': item.get('like_count') or 0,
                'comment_count': item.get('comment_count') or 0,
                'source_page': page,
            },
        )
        return True

    def _translate_all(self):
        """把快照翻成其它语言，写进 translations

        译文来自本地人工词表（locale/<语言>/hardcoded.json，见 Web/services/translate.py）；
        词表里没有的文本保持原样（渲染时回退中文原文），所以可以随时补词表再重刷。
        """
        target_langs = [code for code, _name in settings.LANGUAGES
                        if translate_service.is_enabled(code)]
        if not target_langs:
            self.stdout.write('翻译后端已关闭（TRANSLATE_PROVIDER 为空），跳过翻译')
            return

        rows = list(HaijiaoTopicSnapshot.objects.all())
        for lang in target_langs:
            texts = []
            for row in rows:
                texts += [row.title, row.node_name, row.category]
            outputs = translate_service.translate(texts, lang)
            hit = 0
            with transaction.atomic():
                for index, row in enumerate(rows):
                    data = dict(row.translations or {})
                    # 只在词表命中（译文与原文不同）时才落库，空值渲染时回退原文
                    data[lang] = {
                        'title': outputs[index * 3] if outputs[index * 3] != row.title else '',
                        'node': (outputs[index * 3 + 1]
                                 if outputs[index * 3 + 1] != row.node_name else ''),
                        'category': (outputs[index * 3 + 2]
                                     if outputs[index * 3 + 2] != row.category else ''),
                    }
                    if any(data[lang].values()):
                        hit += 1
                    row.translations = data
                    row.save(update_fields=['translations', 'updated_time'])
            self.stdout.write(f'{lang}：共 {len(rows)} 条，其中 {hit} 条命中词表')
