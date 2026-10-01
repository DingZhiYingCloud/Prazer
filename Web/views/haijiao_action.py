"""海角社区的「写」操作：签到 / 点赞 / 关注 / 打赏 / 收藏

全部需要登录态，全部只挂在 /haijiao/ 前缀下；操作完把结果写进 Django messages
再跳回原页面（POST-Redirect-GET），避免刷新重复提交。

⚠️ 这些接口会**真实作用于海角源站账号**：签到会到账金币、打赏会真实扣费。
所以每一处都在页面上写清后果，不做静默提交。

URL 形态（都是 POST）：
    /haijiao/action/sign-in.html        每日签到
    /haijiao/action/like.html           点赞 / 取消点赞
    /haijiao/action/follow.html         关注 / 取消关注
    /haijiao/action/give.html           打赏
    /haijiao/action/favorite.html       收藏 / 取消收藏帖子
    /haijiao/action/favorite-folder.html 收藏夹：新建 / 重命名 / 删除
"""
import logging

from django.contrib import messages
from django.shortcuts import redirect

from API.apis import haijiao
from Web.services import haijiao_auth

logger = logging.getLogger(__name__)


def _back(request, fallback, message, level='success'):
    """写完把结果塞进 messages 再跳回去（POST-Redirect-GET）"""
    getattr(messages, level)(request, message)
    return redirect(haijiao_auth.safe_next(request, fallback))


def _topic_fallback(topic_id):
    """操作对象是帖子时，跳回帖子详情页"""
    return f'/haijiao/topic/{topic_id}.html' if str(topic_id).isdigit() else '/haijiao/list.html'


@haijiao_auth.login_required
def haijiao_sign_in(request):
    """每日签到（源站 20 金币/天；当天重复调用由源站判为已签到）"""
    if request.method != 'POST':
        return redirect('/haijiao/me.html')
    account = request.hj_account
    data, msg = haijiao.sign_in(account['user_id'], account['token'])
    if data is None:
        return _back(request, '/haijiao/me.html', f'签到失败：{msg}', 'error')

    state = data.get('state')
    if state == 'signed':
        return _back(request, '/haijiao/me.html', f'签到成功，金币 +{data.get("amount") or 0}')
    if state == 'already':
        return _back(request, '/haijiao/me.html', '今天已经签到过了，明天再来', 'info')
    return _back(request, '/haijiao/me.html', '签到任务暂时未开放', 'info')


@haijiao_auth.login_required
def haijiao_like(request):
    """点赞 / 取消点赞（帖子详情页按钮）"""
    if request.method != 'POST':
        return redirect('/haijiao/list.html')
    topic_id = (request.POST.get('topic_id') or '').strip()
    fallback = _topic_fallback(topic_id)
    if not topic_id:
        return _back(request, fallback, '缺少帖子 ID', 'error')

    action = 'unlike' if request.POST.get('action') == 'unlike' else 'like'
    account = request.hj_account
    data, msg = haijiao.like_topic(account['user_id'], account['token'], topic_id, action)
    if data is None:
        return _back(request, fallback, f'操作失败：{msg}', 'error')
    return _back(request, fallback, '已点赞' if data.get('liked') else '已取消点赞')


@haijiao_auth.login_required
def haijiao_follow(request):
    """关注 / 取消关注用户（帖子里的作者）"""
    if request.method != 'POST':
        return redirect('/haijiao/list.html')
    target_user_id = (request.POST.get('target_user_id') or '').strip()
    fallback = (request.POST.get('next') or '/haijiao/list.html').strip()
    if not target_user_id.isdigit():
        return _back(request, fallback, '缺少用户 ID', 'error')

    action = 'unfollow' if request.POST.get('action') == 'unfollow' else 'follow'
    account = request.hj_account
    data, msg = haijiao.follow_user(account['user_id'], account['token'], target_user_id, action)
    if data is None:
        return _back(request, fallback, f'操作失败：{msg}', 'error')
    return _back(request, fallback, '已关注' if data.get('followed') else '已取消关注')


@haijiao_auth.login_required
def haijiao_give(request):
    """打赏：给帖子作者送一份礼物（**真实扣金币 / 钻石**）"""
    if request.method != 'POST':
        return redirect('/haijiao/list.html')
    topic_id = (request.POST.get('topic_id') or '').strip()
    fallback = _topic_fallback(topic_id)
    if not topic_id:
        return _back(request, fallback, '缺少帖子 ID', 'error')

    kind = 'diamond' if request.POST.get('kind') == 'diamond' else 'gold'
    item_id = (request.POST.get('item_id') or '').strip() or None
    quantity = request.POST.get('quantity') or '1'
    if not str(quantity).isdigit() or not (1 <= int(quantity) <= 99):
        return _back(request, fallback, '数量需要是 1~99 的整数', 'error')

    account = request.hj_account
    data, msg = haijiao.give_gift(account['user_id'], account['token'],
                                  topic_id, item_id, int(quantity), kind)
    if data is None:
        return _back(request, fallback, f'打赏失败：{msg}', 'error')
    item = data.get('item') or {}
    # money 是余额字典（{'gold': 35, 'diamond': 0}），不是数字，别直接拼进提示里
    money = data.get('money') or {}
    balance = money.get(kind if kind in ('gold', 'diamond') else 'gold') if isinstance(money, dict) else money
    return _back(request, fallback,
                 f'打赏成功：{item.get("name") or "礼物"} × {data.get("quantity") or quantity}，'
                 f'共花费 {data.get("total_cost") or 0}，余额 {balance}')


# 源站对收藏夹名称的限制（1-12 位字符）：本地先卡一道，省一次注定被拒的请求
FOLDER_NAME_MAX = 12
# 收藏夹相关写操作的默认回跳页
FAVORITES_PAGE = '/haijiao/me/favorites.html'


@haijiao_auth.login_required
def haijiao_favorite(request):
    """收藏 / 取消收藏帖子（帖子详情页按钮）

    action=add 时 folder_id 缺省或 0 = 默认收藏夹（源站语义；注意与
    「我收藏的帖子」里 0＝全部收藏的含义不同）。
    重复收藏源站也回成功，所以这里不先查再收。
    """
    if request.method != 'POST':
        return redirect('/haijiao/list.html')
    topic_id = (request.POST.get('topic_id') or '').strip()
    fallback = _topic_fallback(topic_id)
    if not topic_id.isdigit():
        return _back(request, fallback, '缺少帖子 ID', 'error')

    account = request.hj_account
    if request.POST.get('action') == 'remove':
        data, msg = haijiao.delete_favorite(account['user_id'], account['token'], topic_id)
        if data is None:
            return _back(request, fallback, f'取消收藏失败：{msg}', 'error')
        return _back(request, fallback, '已取消收藏')

    folder_id = (request.POST.get('folder_id') or '').strip() or '0'
    if not folder_id.isdigit():
        folder_id = '0'
    data, msg = haijiao.add_favorite(account['user_id'], account['token'], topic_id, folder_id)
    if data is None:
        return _back(request, fallback, f'收藏失败：{msg}', 'error')
    return _back(request, fallback,
                 '已收藏到默认收藏夹' if folder_id == '0' else '已收藏')


@haijiao_auth.login_required
def haijiao_favorite_folder(request):
    """收藏夹管理：新建 / 重命名 / 删除

    两个入口共用这一个视图：
      - 「我的收藏」页：新建 / 重命名 / 删除
      - 帖子详情页：新建（表单里带 topic_id 时，建完顺手把这帖收进新夹）

    名称先按源站规则本地校验（1-12 位）。删除只对空夹生效：源站对非空夹会
    拒绝，这里把源站的原因原样带回给访客。

    ⚠️ 源站的名字占用缺陷：夹子改名或删除后旧名字不释放，再用同名新建会报
    「已存在!」——页面上已写明，这里不做特殊处理。
    """
    if request.method != 'POST':
        return redirect(FAVORITES_PAGE)
    action = request.POST.get('action') or 'add'
    folder_id = (request.POST.get('folder_id') or '').strip()
    folder_name = (request.POST.get('folder_name') or '').strip()
    topic_id = (request.POST.get('topic_id') or '').strip()
    # 兜底回跳用常量或从 topic_id 推导：页面传来的 next（可能是 ?folder_id= 的当前页）
    # 由 _back → safe_next 收敛后再用，避免把访客可控的字符串当跳转目标（开放重定向）。
    fallback = _topic_fallback(topic_id) if topic_id.isdigit() else FAVORITES_PAGE

    account = request.hj_account
    user_id, token = account['user_id'], account['token']

    if action == 'add':
        if not 1 <= len(folder_name) <= FOLDER_NAME_MAX:
            return _back(request, fallback, f'收藏夹名称需要 1~{FOLDER_NAME_MAX} 位字符', 'error')
        data, msg = haijiao.add_favorite_folder(user_id, token, folder_name)
        if data is None:
            return _back(request, fallback, f'新建失败：{msg}', 'error')

        # 详情页进来的（带 topic_id）：建完直接把帖子收进新夹，省得访客再选一次。
        new_folder_id = str(data.get('folder_id') or '')
        if topic_id.isdigit() and new_folder_id:
            fav_data, fav_msg = haijiao.add_favorite(user_id, token, topic_id, new_folder_id)
            if fav_data is None:
                return _back(request, fallback,
                             f'已新建《{folder_name}》，但收藏这帖失败：{fav_msg}', 'error')
            return _back(request, fallback, f'已新建《{folder_name}》并收藏')
        return _back(request, fallback, f'已新建收藏夹《{folder_name}》')

    if not folder_id.isdigit() or int(folder_id) < 1:
        return _back(request, fallback, '缺少收藏夹 ID', 'error')

    if action == 'rename':
        if not 1 <= len(folder_name) <= FOLDER_NAME_MAX:
            return _back(request, fallback, f'收藏夹名称需要 1~{FOLDER_NAME_MAX} 位字符', 'error')
        data, msg = haijiao.rename_favorite_folder(user_id, token, folder_id, folder_name)
        return (_back(request, fallback, f'已改名为《{folder_name}》') if data is not None
                else _back(request, fallback, f'改名失败：{msg}', 'error'))

    if action == 'delete':
        data, msg = haijiao.delete_favorite_folder(user_id, token, folder_id)
        return (_back(request, fallback, '已删除收藏夹') if data is not None
                else _back(request, fallback, f'删除失败：{msg}', 'error'))

    return _back(request, fallback, '未知操作', 'error')

