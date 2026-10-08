# 项目URL配置（根）
#
# 多语言：页面路由统一包在 i18n_patterns 里，带语言前缀（/pt-br/、/zh-hans/；默认葡语）。
# 工具类端点（/pic/、/download、/feedback、/sitemap.xml、/robots.txt、静态与媒体）保持无前缀，
# 这样它们在各语言下都是同一个地址，也不用被语言切换影响。
# 根路径 / 交给 RedirectView：按 LocaleMiddleware 协商出的语言，跳到对应前缀的首页。
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.urls import include, path, re_path
from django.views.generic import RedirectView, TemplateView
from django.views.static import serve

from Web.views import request as bz_request
from Web.views.urls import page_urlpatterns
from Web.views.urls import urlpatterns as web_urlpatterns

urlpatterns = [
    # 根路径跳当前语言的首页：按 LocaleMiddleware 协商出的语言反向解析 'home'。
    # 协商顺序（/ 没有语言前缀，所以从第 2 步开始）：会话 → django_language cookie
    # → Accept-Language → LANGUAGE_CODE（仍是 pt-br，作为新访客的兜底）。
    # 不能写成 RedirectView(url='/pt-br/')：那样会把已选中文的用户硬拽回葡语，
    # 相当于每次只输域名都重置语言。
    path('', RedirectView.as_view(pattern_name='home', permanent=False)),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),
    path('sitemap.xml', bz_request.sitemap, name='sitemap'),
    # 语言切换端点：POST /i18n/setlang/（django.conf.urls.i18n 提供 set_language）
    path('i18n/', include('django.conf.urls.i18n')),
    # 语言无关的工具端点（图片代理 / 下载 / 意见反馈）
    *web_urlpatterns,
]

# 页面路由：带语言前缀（/pt-br/... 与 /zh-hans/...）
urlpatterns += i18n_patterns(*page_urlpatterns)

# 自定义错误页处理（DEBUG=False 时生效）
handler404 = 'Web.views.request.error_404'
handler500 = 'Web.views.request.error_500'

# 静态文件 & 媒体文件服务
# DEBUG=True 时 Django 自动通过 static() 辅助函数服务
# DEBUG=False 时 static() 返回空列表，需要手动添加路由
if not settings.DEBUG:
    # 静态文件：从 STATICFILES_DIRS 源目录直接服务
    static_root = settings.STATICFILES_DIRS[0] if settings.STATICFILES_DIRS else settings.STATIC_ROOT
    urlpatterns += [
        re_path(r'^static/(?P<path>.*)$', serve, {'document_root': static_root}),
    ]
    # 媒体文件：从 MEDIA_ROOT 直接服务
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
else:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
