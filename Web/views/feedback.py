"""问题反馈入口

只负责一次跳转：把小影托管的反馈页地址交给浏览器。本站没有登录体系，
用户以游客身份匿名提交，无需票据（详见 Web/services/feedback.py 顶部说明）。
"""
from django.shortcuts import redirect

from Web.services import feedback


def entry(request):
    """「意见反馈」入口：302 跳到小影反馈页"""
    return redirect(feedback.feedback_url())
