# 项目URL配置
from django.urls import path, re_path

from Web.views import pic, request

urlpatterns = [
    path('', request.index, name='home'),
    path('index/', request.index, name='index'),
    # 图片代理：把第三方海报换成本站地址（本地缓存 + 压缩，见 Web/views/pic.py）
    path('pic/<str:sig>.webp', pic.pic, name='pic'),
    # 分类列表：第 1 页不带页码（收录地址更干净），第 2 页起带页码
    path('list/<int:type_id>.html', request.movie_list, name='movie_list'),
    path('list/<int:type_id>/<int:page>.html', request.movie_list, name='movie_list_page'),
    path('detail/<str:vod_id>.html', request.detail, name='movie_detail'),
    path('play/<str:vod_id>/<str:sid>/<str:nid>.html', request.play, name='movie_play'),
    # 搜索：关键词可能带斜杠（如 "AC/DC"），WSGI 会把 %2F 解码成 /，
    # <str:keyword> 默认不匹配斜杠，所以用非贪婪的 .+? 兜住。
    #
    # 下面这条「带页码」的规则必须排在前面的不带页码规则之前：
    # 否则 /so/爱情/2.html 会被 .+? 连页码一起吃进关键词（变成搜 "爱情/2"）。
    re_path(r'^so/(?P<keyword>.+?)/(?P<page>\d+)\.html$', request.search, name='search_page'),
    re_path(r'^so/(?P<keyword>.+?)\.html$', request.search, name='search'),
]
