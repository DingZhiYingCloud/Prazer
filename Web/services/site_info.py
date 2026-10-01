"""站点信息 context processor

职责：把 .env 里配置的站点名称、联系方式注入全站模板，
使二开者只需修改 .env（不改任何模板）即可完成改名与换联系方式。

模板中可直接使用：
    {{ SITE_NAME }}           站点主名称（如 小影影视）
    {{ SITE_NAME_ALT }}       站点副名称（如 小影电影，可为空）
    {{ SITE_BRAND }}          SEO 文案用的品牌组合短语（如 小影电影（小影影视））
    {{ SITE_CONTACT_EMAIL }}  联系邮箱
    {{ SITE_CONTACT_WECHAT }} 微信号
    {{ SITE_CONTACT_TG }}     Telegram
    {{ STATIC_VERSION }}      output.css 的版本号（文件修改时间，用于刷新浏览器缓存）
    {{ FEEDBACK_API_BASE }}   小影反馈中心基础地址（「开发者联系方式」弹窗走它的免签接口）
    {{ FEEDBACK_APP_ID }}     本站在小影「接入项目」里的 APPID（反馈数据按它归属）
"""
import os

from django.conf import settings

from Web.services import feedback


def _static_version():
    """output.css 的修改时间，拿来当版本号

    为什么要这个：模板里写死 /static/css/output.css 的话，浏览器会一直用缓存里的旧文件。
    而 output.css 是编译产物，模板里新增 Tailwind/daisyUI 类名后必须重编译，
    旧文件里没有那些类名，表现就是"功能写了但看不到"。
    取文件修改时间可以让版本号随重编译自动变化，不用人工记着改。

    取不到文件时返回 0，绝不因为读不到一个文件就让整站起不来。
    """
    path = os.path.join(settings.STATICFILES_DIRS[0], 'css', 'output.css')
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return 0


def site_info(request):
    """向全站模板注入站点信息变量（取值见 settings.py 中同名配置，最终来源为 .env）"""
    return {
        'SITE_NAME': settings.SITE_NAME,
        'SITE_NAME_ALT': settings.SITE_NAME_ALT,
        'SITE_BRAND': settings.SITE_BRAND,
        'SITE_CONTACT_EMAIL': settings.SITE_CONTACT_EMAIL,
        'SITE_CONTACT_WECHAT': settings.SITE_CONTACT_WECHAT,
        'SITE_CONTACT_TG': settings.SITE_CONTACT_TG,
        'STATIC_VERSION': _static_version(),
        # 问题反馈中心（小影统一反馈系统）：模板用它渲染「开发者联系方式」弹窗
        'FEEDBACK_API_BASE': feedback.FEEDBACK_BASE,
        'FEEDBACK_APP_ID': feedback.FEEDBACK_APP_ID,
    }
