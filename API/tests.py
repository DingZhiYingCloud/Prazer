"""小影接口层测试：签名算法、文案清洗、失败降级

全部离线执行（网络请求一律 mock），不依赖小影接口是否可用 ——
测试要能天天跑，不能因为对方服务抖动就红。
"""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from API.apis import movie
from API.common import signature

LOCMEM_CACHE = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
}


class SignatureTests(SimpleTestCase):
    """签名必须与服务端口径一致：过滤空值 → 键名升序 → k=v&k=v → HMAC-SHA256 小写 hex"""

    def test_matches_known_vector(self):
        with mock.patch.object(signature, 'APP_SECRET', 's3cr3t'):
            self.assertEqual(
                signature.sign_params({'b': '2', 'a': '1'}),
                '97ddaa0aba6d1b8e0949c91863908817006da2a19ffcae88d4503fb53f8ebeb4',
            )

    def test_order_and_empty_values_do_not_matter(self):
        with mock.patch.object(signature, 'APP_SECRET', 's3cr3t'):
            one = signature.sign_params({'a': '1', 'b': '2'})
            two = signature.sign_params({'b': '2', 'a': '1', 'empty': '', 'none': None})
            self.assertEqual(one, two)

    def test_sign_excludes_existing_sign(self):
        with mock.patch.object(signature, 'APP_SECRET', 's3cr3t'):
            self.assertEqual(
                signature.sign_params({'a': '1', 'b': '2', 'sign': 'x'}),
                signature.sign_params({'a': '1', 'b': '2'}),
            )

    def test_auth_params_adds_public_params(self):
        with mock.patch.object(signature, 'APP_ID', 'app_test'), \
                mock.patch.object(signature, 'APP_SECRET', 's3cr3t'):
            params = signature.auth_params({'vod_id': 1})
            self.assertEqual(params['app_id'], 'app_test')
            self.assertEqual(len(params['timestamp']), 10)
            self.assertEqual(len(params['nonce']), 16)
            self.assertEqual(params['sign'], signature.sign_params(params))

    def test_auth_params_without_credentials(self):
        """没配凭证时原样返回业务参数：接口会回 20011，由调用方降级，不该在这里报错"""
        with mock.patch.object(signature, 'APP_ID', ''), \
                mock.patch.object(signature, 'APP_SECRET', ''):
            self.assertEqual(signature.auth_params({'vod_id': 1}), {'vod_id': 1})


class CleanTextTests(SimpleTestCase):
    """源站文案带多层转义的实体垃圾，必须在取数时清掉"""

    def test_strips_entity_junk(self):
        self.assertEqual(movie.clean_text('&amp;amp;  ; &amp;amp;'), '')

    def test_unescapes_real_entities(self):
        # 真实体要还原；句中被空格包围的孤立 & 属于垃圾，会被清掉
        self.assertEqual(movie.clean_text('A &amp; B &lt;C&gt;'), 'A B <C>')

    def test_keeps_normal_ampersand_in_word(self):
        self.assertEqual(movie.clean_text('AT&T 出品'), 'AT&T 出品')

    def test_collapses_whitespace(self):
        self.assertEqual(movie.clean_text('  多个   空格\n换行  '), '多个 空格 换行')

    def test_url_is_left_untouched(self):
        """播放地址里的 & 与长度不能被清洗改坏"""
        url = 'https://cdn.example.com/a/b.m3u8?sign=abc&t=1'
        self.assertEqual(movie.clean_payload({'m3u8': url})['m3u8'], url)
        self.assertEqual(movie.clean_text(url), url)


@override_settings(CACHES=LOCMEM_CACHE)
class CacheFallbackTests(SimpleTestCase):
    """接口失败时的降级：有旧数据用旧数据，没有任何数据才返回 None"""

    def setUp(self):
        cache.clear()

    def test_success_writes_cache_and_stale_backup(self):
        payload = {'code': movie.SUCCESS_CODE, 'data': {'name': '测试'}}
        with mock.patch.object(movie, 'signed_get', return_value=payload):
            self.assertEqual(movie._cached('k', 60, '/p'), {'name': '测试'})
        self.assertEqual(cache.get('k'), {'name': '测试'})
        self.assertEqual(cache.get('k' + movie.STALE_SUFFIX), {'name': '测试'})

    def test_failure_returns_stale_backup(self):
        cache.set('k' + movie.STALE_SUFFIX, {'name': '旧数据'}, 60)
        with mock.patch.object(movie, 'signed_get', side_effect=OSError('boom')):
            self.assertEqual(movie._cached('k', 60, '/p'), {'name': '旧数据'})

    def test_failure_without_backup_returns_none(self):
        with mock.patch.object(movie, 'signed_get', side_effect=OSError('boom')):
            self.assertIsNone(movie._cached('k', 60, '/p'))

    def test_business_error_code_is_treated_as_failure(self):
        payload = {'code': 20011, 'msg': '签名错误', 'data': {}}
        with mock.patch.object(movie, 'signed_get', return_value=payload):
            self.assertIsNone(movie._cached('k', 60, '/p'))
        self.assertIsNone(cache.get('k'))

    def test_timeout_is_passed_through(self):
        """播放接口要单独用更宽的超时（回源解析 m3u8 比数据接口慢）"""
        payload = {'code': movie.SUCCESS_CODE, 'data': {'m3u8': 'x'}}
        with mock.patch.object(movie, 'signed_get', return_value=payload) as fake:
            movie._cached('k', 60, '/p', {'a': 1}, timeout=movie.PLAY_TIMEOUT)
        self.assertEqual(fake.call_args.kwargs['timeout'], movie.PLAY_TIMEOUT)
        self.assertGreater(movie.PLAY_TIMEOUT, signature.REQUEST_TIMEOUT)

    def test_get_list_passes_all_filters(self):
        """列表筛选参数要原样带给接口（少传一个就等于筛选不生效）"""
        payload = {'code': movie.SUCCESS_CODE, 'data': {'items': []}}
        with mock.patch.object(movie, 'signed_get', return_value=payload) as fake:
            movie.get_list(2, page=3, order='hits', year='2025', area='大陆',
                           genre='动作', lang='国语')
        self.assertEqual(fake.call_args.args[1], {
            'type_id': 2, 'page': 3, 'order': 'hits', 'year': '2025',
            'area': '大陆', 'genre': '动作', 'lang': '国语',
        })

    def test_get_filters_uses_type_id(self):
        payload = {'code': movie.SUCCESS_CODE, 'data': {'sub_types': [], 'groups': []}}
        with mock.patch.object(movie, 'signed_get', return_value=payload) as fake:
            movie.get_filters(2)
        self.assertEqual(fake.call_args.args[1], {'type_id': 2})
        self.assertTrue(fake.call_args.args[0].endswith('/filters'))
