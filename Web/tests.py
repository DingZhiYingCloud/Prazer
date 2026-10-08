"""页面层测试：路由、模板渲染、降级展示、图片代理

小影接口一律 mock 掉，测试只关心"我们这层"的行为：
    数据正常时页面渲染出关键内容；数据缺失时不报 500 而是降级；
    图片代理的签名与失败兜底按预期工作。
"""
import pathlib
from unittest import mock

from django.test import TestCase, override_settings

from Web.views.pic import pic_url, sign

# 模板目录（用于"多行 {# #} 注释"这类静态检查）
TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent / 'templates'

# 测试用内存缓存：避免测试往项目 cache/ 目录里写文件。
# 注意：override_settings 会**整体替换** CACHES，所以会话用的独立别名
# （settings.SESSION_CACHE_ALIAS = 'sessions'）也必须一并给出，
# 否则 SessionMiddleware 取不到该别名，每个请求都会直接 500。
LOCMEM_CACHE = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'sessions': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
}

HOME_DATA = {
    'carousel': [
        {'id': '1', 'name': '测试影片A', 'note': '已完结', 'cover': 'https://img.example.com/a.jpg',
         'intro': '简介A'},
        {'id': '2', 'name': '测试影片B', 'note': '第2集', 'cover': 'https://img.example.com/b.jpg',
         'intro': '简介B'},
    ],
    'blocks': [
        {'title': '追剧周表', 'items': [
            {'id': '1', 'name': '测试影片A', 'cover': 'https://img.example.com/a.jpg', 'note': '已完结'},
            {'id': '2', 'name': '测试影片B', 'cover': 'https://img.example.com/b.jpg', 'note': '第2集'},
        ]},
    ],
}

LIST_DATA = {
    'items': [{'id': '1', 'name': '测试影片A', 'cover': 'https://img.example.com/a.jpg', 'note': '已完结'}],
    'pagination': {'current': 1, 'total': 3},
}

# 筛选接口的返回结构（子分类 + 地区/年份/排序组），只要 options[].value 与 name
FILTERS_DATA = {
    'type_id': 2,
    'sub_types': [{'name': '热门连续剧', 'value': '13'}, {'name': '日韩剧', 'value': '44'}],
    'groups': [
        {'key': 'area', 'name': '地区', 'options': [{'name': '大陆', 'value': '大陆'},
                                                 {'name': '韩国', 'value': '韩国'}]},
        {'key': 'year', 'name': '年份', 'options': [{'name': '2025', 'value': '2025'}]},
        {'key': 'order', 'name': '排序', 'options': [{'name': '按时间', 'value': 'time'}]},
    ],
}

CATEGORIES_DATA = {
    'main': [{'id': 2, 'name': '连续剧'}],
    'sub': [{'id': 13, 'name': '热门连续剧'}],
    'labels': [{'key': 'netflix', 'name': 'Netflix 专区'}],
}

DETAIL_DATA = {
    'id': '1',
    'name': '测试影片A',
    'cover': 'https://img.example.com/a.jpg',
    'intro': '这是简介',
    'info': {'导演': '张三/李四/', '主演': '王五/', '上映': '2026-09-11', '豆瓣': '0.0分'},
    'sources': [{'sid': '1', 'name': '线路一', 'episodes': [{'sid': '1', 'nid': '1'}]}],
}


class TemplateCommentTests(TestCase):
    """模板里不许出现多行 {# #} 注释

    Django 的 {# #} 只支持单行；写成两行会被当成正文原样输出到页面上，
    而且这种"漏出来的注释"在 CSS Grid / Flex 里还会变成占位的匿名元素（曾把首页卡片挤歪）。
    这个坑踩过两次，固化成测试，改模板时立刻能发现。多行说明请用 {% comment %}。
    """

    def test_no_multiline_hash_comment(self):
        offenders = []
        for path in TEMPLATE_DIR.rglob('*.html'):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if line.count('{#') > line.count('#}'):
                    offenders.append('%s:%d' % (path.relative_to(TEMPLATE_DIR.parent.parent), number))
        self.assertEqual(offenders, [], '这些地方的多行 {# #} 注释会漏到页面上，请改成 {% comment %}')


class OfflinePageMixin:
    """页面测试一律不联网

    渲染时模板的 context processor（分类导航、友情链接）与友情链接中间件都会去打接口，
    这里统一换成本地数据；各视图自己的取数（首页/列表/详情/筛选）由各用例单独 mock。
    """

    def setUp(self):
        super().setUp()
        for target, value in (
            ('API.apis.movie.get_categories', CATEGORIES_DATA),
            ('Web.services.friend_links.get_friend_links', []),
            ('Web.middleware.get_friend_links', []),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)


class PageRenderTests(OfflinePageMixin, TestCase):
    def test_home_renders_carousel_and_cards(self):
        with mock.patch('Web.views.request.movie.get_home', return_value=HOME_DATA):
            resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('测试影片A', html)
        self.assertIn('xy-film-card', html)          # 首页卡片用的是胶片格样式
        self.assertIn('/pic/', html)                  # 图片走本站代理

    def test_home_degrades_when_api_unavailable(self):
        """接口挂了也要 200 + 友好提示，不能把异常抛给访客"""
        with mock.patch('Web.views.request.movie.get_home', return_value=None):
            resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('影片数据暂时获取不到', resp.content.decode())

    def test_list_page_one_redirects_to_clean_url(self):
        with mock.patch('Web.views.request.movie.get_list', return_value=LIST_DATA):
            resp = self.client.get('/list/1/1.html')
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp['Location'], '/list/1.html')

    def test_list_page_two_has_page_in_title(self):
        with mock.patch('Web.views.request.movie.get_filters', return_value=FILTERS_DATA), \
                mock.patch('Web.views.request.movie.get_list', return_value=LIST_DATA):
            resp = self.client.get('/list/1/2.html')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('第 2 页', resp.content.decode())

    def test_detail_renders_movie_json_ld_and_og_image(self):
        with mock.patch('Web.views.request.movie.get_detail', return_value=DETAIL_DATA):
            resp = self.client.get('/detail/1.html')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('application/ld+json', html)
        self.assertIn('"@type":"Movie"', html)
        self.assertIn('"datePublished":"2026-09-11"', html)
        self.assertIn('property="og:image"', html)

    def test_detail_returns_404_when_missing(self):
        with mock.patch('Web.views.request.movie.get_detail', return_value=None):
            resp = self.client.get('/detail/1.html')
        self.assertEqual(resp.status_code, 404)


@override_settings(CACHES=LOCMEM_CACHE)
class ListFilterTests(OfflinePageMixin, TestCase):
    """列表页筛选：选项来自筛选接口、非法值被白名单挡掉、条件之间互相保留"""

    def fetch(self, query='', filters=FILTERS_DATA):
        with mock.patch('Web.views.request.movie.get_filters', return_value=filters), \
                mock.patch('Web.views.request.movie.get_list', return_value=LIST_DATA) as fake_list:
            resp = self.client.get('/list/2.html' + query)
        return resp, fake_list.call_args.kwargs

    def test_no_filter_passes_nothing_to_api(self):
        _, kwargs = self.fetch()
        for key in ('order', 'year', 'area', 'genre', 'lang'):
            self.assertIsNone(kwargs[key])

    def test_valid_filter_is_passed_through(self):
        _, kwargs = self.fetch('?area=%E5%A4%A7%E9%99%86')   # area=大陆
        self.assertEqual(kwargs['area'], '大陆')

    def test_unknown_filter_value_is_dropped(self):
        """不在接口可选值里的筛选值一律丢弃：否则随便造值就能占一份缓存并回源"""
        _, kwargs = self.fetch('?area=乱写的&year=1999')
        self.assertIsNone(kwargs['area'])
        self.assertIsNone(kwargs['year'])

    def test_hits_order_is_available_again(self):
        resp, kwargs = self.fetch('?order=hits')
        self.assertEqual(kwargs['order'], 'hits')
        self.assertIn('按人气', resp.content.decode())

    def test_filter_bar_renders_options_and_sub_types(self):
        resp, _ = self.fetch()
        html = resp.content.decode()
        self.assertIn('更多筛选', html)
        self.assertIn('地区', html)
        self.assertIn('/list/13.html', html)          # 子分类是独立列表页
        self.assertIn('热门连续剧', html)

    def test_selected_filters_are_kept_in_links(self):
        """点某个筛选时，其它条件要保留（换地区不该把排序丢掉）"""
        resp, _ = self.fetch('?area=%E5%A4%A7%E9%99%86&order=hits')
        html = resp.content.decode()
        self.assertIn('已选：地区 大陆', html)
        self.assertIn('order=hits', html)
        self.assertIn('%E5%A4%A7%E9%99%86', html)

    def test_sub_category_name_is_resolved(self):
        """子分类页（如 /list/13.html）要显示"热门连续剧"，而不是兜底的"影视分类" """
        resp, _ = self.fetch()
        self.assertIn('连续剧', resp.content.decode())
        with mock.patch('Web.views.request.movie.get_filters', return_value={}), \
                mock.patch('Web.views.request.movie.get_list', return_value=LIST_DATA), \
                mock.patch('Web.views.request.movie.get_categories', return_value=CATEGORIES_DATA):
            resp = self.client.get('/list/13.html')
        self.assertIn('热门连续剧', resp.content.decode())

    def test_filters_api_down_still_renders_page(self):
        """筛选接口挂了也要能出页面（只是没有筛选栏），不能把访客挡在门外"""
        resp, kwargs = self.fetch('?area=大陆', filters=None)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(kwargs['area'])


@override_settings(CACHES=LOCMEM_CACHE)
class PicUrlTests(TestCase):
    def test_local_and_empty_urls_are_untouched(self):
        self.assertEqual(pic_url(''), '')
        self.assertEqual(pic_url('/media/logo.png'), '/media/logo.png')
        self.assertEqual(pic_url('not-a-url'), 'not-a-url')

    def test_remote_url_becomes_signed_proxy_url(self):
        url = 'https://img.example.com/a.jpg'
        proxied = pic_url(url)
        self.assertTrue(proxied.startswith(f'/pic/{sign(url)}.webp?u='))

    def test_bad_signature_is_rejected(self):
        url = 'https://img.example.com/a.jpg'
        resp = self.client.get('/pic/deadbeefdeadbeefdead.webp', {'u': url})
        self.assertEqual(resp.status_code, 404)

    def test_missing_url_param_is_rejected(self):
        resp = self.client.get(f'/pic/{sign("https://img.example.com/a.jpg")}.webp')
        self.assertEqual(resp.status_code, 404)

    def test_falls_back_to_original_url_when_download_fails(self):
        """回源失败不能让访客看到破图：302 到原图地址，和没有代理时一样"""
        url = 'https://img.example.com/a.jpg'
        with mock.patch('Web.views.pic.requests.get', side_effect=OSError('boom')):
            resp = self.client.get(f'/pic/{sign(url)}.webp', {'u': url})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], url)

    def test_failed_url_is_not_retried_immediately(self):
        """失败过的地址短期不再回源：源站挂掉时不能每个访客都占着 worker 干等"""
        url = 'https://img.example.com/dead.jpg'
        with mock.patch('Web.views.pic.requests.get', side_effect=OSError('boom')) as fake:
            self.client.get(f'/pic/{sign(url)}.webp', {'u': url})
            self.client.get(f'/pic/{sign(url)}.webp', {'u': url})
        self.assertEqual(fake.call_count, 1)
