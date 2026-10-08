"""多语言页面的 <head> 辅助（hreflang 备选地址）

页面路由都带语言前缀（/pt-br/、/zh-hans/），所以要在 <head> 里用 hreflang
告诉搜索引擎"这些地址是同一页的不同语言版本"。

只对**带语言前缀的页面路径**输出（工具类端点 /download、/pic/ 等没有语言版本，
translate_url 对它们是恒等的，输出会变成一串重复的 alternate，故用
get_language_from_path() 判断后直接跳过）。
"""
from django.conf import settings
from django.urls import translate_url
from django.utils.translation import get_language_from_path


def language_alternates(request):
    """返回 {'language_alternates': [{'code', 'url'}, ...]}（供 template.html 渲染 hreflang）"""
    if get_language_from_path(request.path) is None:
        return {'language_alternates': []}

    alternates = []
    for code, _name in settings.LANGUAGES:
        try:
            url = translate_url(request.path, code)
        except Exception:
            url = ''
        if url:
            alternates.append({'code': code, 'url': url})
    return {'language_alternates': alternates}
