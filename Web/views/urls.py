# 项目URL配置（Web 应用内）
#
# 这里分两份：
#   urlpatterns      —— 语言无关的工具端点（图片代理 / 下载 / 意见反馈），不带语言前缀；
#   page_urlpatterns —— 需要按语言分前缀的页面路由，由根 urls.py 的 i18n_patterns 包裹，
#                       实际地址形如 /pt-br/haijiao/list.html、/zh-hans/haijiao/list.html。
from django.urls import path, re_path

from Web.views import (feedback, haijiao, haijiao_account, haijiao_action, pic,
                       request)

# 语言无关端点
urlpatterns = [
    # 意见反馈：本地入口 302 跳到小影托管的反馈页（见 Web/views/feedback.py）。
    # 走本地路由是为了绕开「外链随机替换」中间件（它会把非本站域名的 <a> 换成友情链接）。
    path('feedback', feedback.entry, name='feedback'),
    # App 下载：全站唯一的下载入口，302 跳到 .env 的 DOWNLOAD_URL（见 request.app_download）。
    # 页头「下载 App」与卡片下载框里的所有平台按钮都指向这里，同样是为了绕开外链替换。
    path('download', request.app_download, name='app_download'),
    # 图片代理：把第三方海报换成本站地址（本地缓存 + 压缩，见 Web/views/pic.py）。
    # 海角卡片封面同样经 {% pic %} 走这里，故必须保留。
    path('pic/<str:sig>.webp', pic.pic, name='pic'),
]

# 按语言分前缀的页面路由
page_urlpatterns = [
    # 首页：直接渲染海角社区「热帖」第 1 页（见 Web/views/haijiao.py 的 haijiao_home）
    path('', haijiao.haijiao_home, name='home'),
    # /index/ 是首页的别名，haijiao_home 会把它收敛回 /
    path('index/', haijiao.haijiao_home, name='index'),

    # ============ 海角社区频道（本站唯一频道）============
    # 列表页沿用「热帖第 1 页 = 首页」收敛模式，详情/播放独立前缀避免与其它线路撞车。
    path('haijiao/list.html', haijiao.haijiao_index, name='haijiao_index'),
    path('haijiao/list/<str:tab>.html', haijiao.haijiao_list, name='haijiao_list'),
    path('haijiao/list/<str:tab>/<int:page>.html', haijiao.haijiao_list, name='haijiao_list_page'),
    path('haijiao/topic/<str:topic_id>.html', haijiao.haijiao_topic, name='haijiao_topic'),
    path('haijiao/play/<str:topic_id>/<str:attachment_id>.html',
         haijiao.haijiao_play, name='haijiao_play'),
    # m3u8 内联的 AES-128 密钥字节：hls.js 不认 data: URI 密钥，播放器改为向这里取
    # （见 Web/views/haijiao.py 的 _rewrite_key_uri 与 haijiao_key）
    path('haijiao/key/<str:token>', haijiao.haijiao_key, name='haijiao_key'),
    # 搜索：网页端不再提供（要连小影接口、无法静态化），改渲染「需在 App 内使用」的拦截页
    path('haijiao/search.html', haijiao.locked_search, name='haijiao_search'),

    # ---- 海角账号体系：网页端不再提供，统一渲染「需在 App 内使用」的拦截页 ----
    # 账号相关操作都要连小影接口，无法静态化；原视图代码保留在 haijiao_account.py /
    # haijiao_action.py 里，恢复网页登录时把这里的 target 换回去即可。
    path('haijiao/register.html', haijiao.locked_login, name='haijiao_register'),
    path('haijiao/login.html', haijiao.locked_login, name='haijiao_login'),
    path('haijiao/logout.html', haijiao_account.haijiao_logout, name='haijiao_logout'),
    path('haijiao/me.html', haijiao.locked_account, name='haijiao_me'),
    path('haijiao/me/topics.html', haijiao.locked_account, name='haijiao_me_topics'),
    path('haijiao/me/liked.html', haijiao.locked_account, name='haijiao_me_liked'),
    path('haijiao/me/favorites.html', haijiao.locked_account, name='haijiao_me_favorites'),
    path('haijiao/me/following.html', haijiao.locked_account, name='haijiao_me_following'),
    path('haijiao/me/fans.html', haijiao.locked_account, name='haijiao_me_fans'),
    path('haijiao/me/wealth.html', haijiao.locked_account, name='haijiao_me_wealth'),

    # ---- 海角社区写操作（签到 / 点赞 / 关注 / 打赏 / 收藏）----
    path('haijiao/action/sign-in.html', haijiao_action.haijiao_sign_in, name='haijiao_sign_in'),
    path('haijiao/action/like.html', haijiao_action.haijiao_like, name='haijiao_like'),
    path('haijiao/action/follow.html', haijiao_action.haijiao_follow, name='haijiao_follow'),
    path('haijiao/action/give.html', haijiao_action.haijiao_give, name='haijiao_give'),
    # 收藏：add/remove 是帖子的收藏状态；favorite-folder 是收藏夹的新建/重命名/删除
    path('haijiao/action/favorite.html', haijiao_action.haijiao_favorite,
         name='haijiao_favorite'),
    path('haijiao/action/favorite-folder.html', haijiao_action.haijiao_favorite_folder,
         name='haijiao_favorite_folder'),
]

# ==================== 以下频道已下架（代码保留，暂不注册路由，访问 404）====================
# 恢复方式：取消下面注释，把它们 appendix 到 page_urlpatterns 即可
# （request / re_path 的 import 已一并保留；恢复后同样走语言前缀）。
#
# # ---- 短剧专区（红果短剧线路，见 API/apis/drama.py）----
# # 列表地址沿用原「短剧」子分类的 /list/125.html，榜单与分类各自是独立频道路径。
# # 分类是两级的：一级 /list/125/<一级>.html，二级题材 /list/125/<一级>/<题材>.html
# # （接口的二级取值本身是「real-drama/romance」这种带斜杠的形式，落到路径上正好是两段）。
# # 这几条必须排在下面 555 的列表路由之前 —— /list/125.html 与 /list/125/<页>.html
# # 两边都能匹配，先注册的先生效；125 已改由红果承载，不能再落到 555 的子分类列表上。
# # （<int:page> 也要排在 <str:key> 之前，否则 /list/125/2.html 会被当成频道名。）
# path('list/125.html', request.drama_list, name='drama_list'),
# path('list/125/<int:page>.html', request.drama_list, name='drama_list_page'),
# path('list/125/<str:key>.html', request.drama_list, name='drama_channel'),
# # 一级分类的分页要排在二级分类之前：/list/125/real-drama/2.html 是「第 2 页」，
# # 而 /list/125/real-drama/romance.html 是「爱情题材」。两者的第二段靠类型区分
# # （题材 slug 不会是纯数字），所以这里用 <int:page> 先吃掉页码那种形式。
# path('list/125/<str:key>/<int:page>.html', request.drama_list, name='drama_channel_page'),
# path('list/125/<str:key>/<str:tag>.html', request.drama_list, name='drama_channel_tag'),
# path('list/125/<str:key>/<str:tag>/<int:page>.html', request.drama_list,
#      name='drama_channel_tag_page'),
# # 短剧搜索：与影视搜索（/so/）是两套独立数据源，所以单独一条路由、独立搜索框。
# path('drama/search.html', request.drama_search, name='drama_search'),
# # 详情与播放单独用 /drama/ 前缀：红果的 series_id 与 555 的 vod_id 是两套编号，
# # 共用 /detail/<id>.html、/play/... 会撞车。
# path('drama/detail/<str:series_id>.html', request.drama_detail, name='drama_detail'),
# path('drama/play/<str:series_id>/<int:ep>.html', request.drama_play, name='drama_play'),
#
# # ---- 影视（555 线路，见 API/apis/movie.py）----
# # 分类列表：第 1 页不带页码（收录地址更干净），第 2 页起带页码
# path('list/<int:type_id>.html', request.movie_list, name='movie_list'),
# path('list/<int:type_id>/<int:page>.html', request.movie_list, name='movie_list_page'),
# path('detail/<str:vod_id>.html', request.detail, name='movie_detail'),
# path('play/<str:vod_id>/<str:sid>/<str:nid>.html', request.play, name='movie_play'),
# # 搜索：关键词可能带斜杠（如 "AC/DC"），WSGI 会把 %2F 解码成 /，
# # <str:keyword> 默认不匹配斜杠，所以用非贪婪的 .+? 兜住。
# #
# # 下面这条「带页码」的规则必须排在前面的不带页码规则之前：
# # 否则 /so/爱情/2.html 会被 .+? 连页码一起吃进关键词（变成搜 "爱情/2"）。
# re_path(r'^so/(?P<keyword>.+?)/(?P<page>\d+)\.html$', request.search, name='search_page'),
# re_path(r'^so/(?P<keyword>.+?)\.html$', request.search, name='search'),
