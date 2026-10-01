"""海角社区登录态（仅作用于 /haijiao/ 频道，站内其它频道不受影响）

设计要点：
1. 会话里只存四样东西：user_id / token / username / nickname。
   token 是海角源站的登录凭证，属于敏感信息，所以放在**服务端会话**里
   （SESSION_ENGINE = cache session，见 settings.py），浏览器只拿 sessionid。
2. 不落库、不建模型、不保存密码：本站对海角账号只做「转交给小影 API」，
   密码提交完就丢，本地只持有登录后的 token。
3. 凭据一律**直传 user_id + user_token**，不使用对方的库内 account_id，
   这样本站的登录/登出边界完全由自己的会话决定。

用法：
    from Web.services import haijiao_auth

    haijiao_auth.login_session(request, data)     # 登录成功后写入会话
    account = haijiao_auth.current(request)       # 未登录返回 None
    haijiao_auth.logout(request)

    @haijiao_auth.login_required                  # 个人中心/写操作用
    def my_view(request): ...
"""
from functools import wraps
from urllib.parse import quote

from django.shortcuts import redirect

# 会话键：一次性放一个 dict，避免多个键各自丢失导致"半登录"状态
SESSION_KEY = 'hj_account'

LOGIN_URL = '/haijiao/login.html'


def login_session(request, data):
    """登录/注册成功后写入会话

    :param data: 接口返回的 data（user_id / token / username / nickname）
    """
    request.session[SESSION_KEY] = {
        'user_id': str(data.get('user_id') or ''),
        'token': data.get('token') or '',
        'username': data.get('username') or '',
        'nickname': data.get('nickname') or '',
    }


def current(request):
    """当前登录账号（dict：user_id / token / username / nickname）；未登录返回 None

    缺 user_id 或缺 token 都视为未登录 —— 源站接口两个都要，缺一个也调不通。
    """
    data = request.session.get(SESSION_KEY) or {}
    if not (data.get('user_id') and data.get('token')):
        return None
    return data


def logout(request):
    """退出登录：只清掉海角账号这一项，不影响会话里的其它内容"""
    request.session.pop(SESSION_KEY, None)


def login_required(view):
    """视图装饰器：未登录跳登录页，并把原地址带在 next 上，登录后跳回去

    同时把账号挂到 request.hj_account，视图里直接用。
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        account = current(request)
        if account is None:
            nxt = quote(request.get_full_path(), safe='')
            return redirect(f'{LOGIN_URL}?next={nxt}')
        request.hj_account = account
        return view(request, *args, **kwargs)

    return wrapper


def safe_next(request, fallback='/haijiao/me.html'):
    """把 next 收敛成站内地址，避免被当成开放跳板（只认 /haijiao/ 开头的相对路径）"""
    target = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if target.startswith('/haijiao/') and '//' not in target:
        return target
    return fallback
