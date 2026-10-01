"""问题反馈中心接入（小影统一反馈系统）

反馈页托管在小影 API 侧（`/feedback/<APPID>/`），本站**零代码接入**：只做两件事 ——

1. 「意见反馈」入口：把用户带到反馈页。本站**没有登录体系**，用户一律以游客身份
   匿名提交，所以不需要「换一次性票据带登录态」那套（有登录态的项目才需要，
   见 BeiZiMusic 的同名模块）。
2. 「开发者联系方式」：前端直接调小影的 `/api/feedback/contacts?app_id=...` 取数据
   （该端点免签名、允许跨域），联系方式由小影后台按项目统一维护。

为什么入口走本地路由 `/feedback` 而不是直接放外链：本站开着「外链随机替换」中间件
（Web/middleware.py），页面里 `<a href="http…">` 只要不是本站域名就会被换成随机
友情链接 —— 直连反馈页的外链会被它劫持。走本地路由再由视图 302 跳转，既绕开中间件，
地址也更干净。
"""
from django.conf import settings

from API.common.signature import API_BASE

# 本项目在小影「接入项目」里的 APPID（决定反馈数据归属哪个项目）
# 取值见 settings.XIAOYING_FEEDBACK_APP_ID（最终来源为 .env）
FEEDBACK_APP_ID = settings.XIAOYING_FEEDBACK_APP_ID

# 反馈页地址前缀（与 API 同源：切线上 / 本地只改 .env 的 XIAOYING_API_BASE）
FEEDBACK_BASE = API_BASE


def feedback_url():
    """反馈页地址（本站无登录态，不需要票据参数）"""
    return f'{FEEDBACK_BASE}/feedback/{FEEDBACK_APP_ID}/'
