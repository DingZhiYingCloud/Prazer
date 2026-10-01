"""海角社区的媒体地址处理（详情页 / 排行榜 / 个人中心共用）

源站把用户头像、帖内图片、视频封面都放在「混淆地址」里（形如 …/<hash>.jpeg.txt），
直接当图片用只会拿到一段文本，必须经 /api/haijiao/image 解密端点转换。

这里集中三件事：
    image_url(url)              混淆地址 → 解密端点地址（不经判断，一律走端点）
    media_url(url)              混淆地址走端点；普通地址原样返回
    avatar_url(node)            头像：看 avatar_encrypted 决定是否解密
    rewrite_content_images(html) 把正文 HTML 里 <img src="混淆地址"> 换成端点地址

调用示例：
    from Web.services import haijiao_media

    haijiao_media.avatar_url(item)                       # 排行榜条目 / 用户名片
    haijiao_media.avatar_url(detail.get('author'))       # 帖子作者
    haijiao_media.media_url(images[0])                   # 列表卡片封面
"""
import re
from urllib.parse import quote

from API.common.signature import API_BASE

# 源站正文里 <img src="混淆地址"> 的 src 属性
_IMG_SRC_RE = re.compile(r'(<img[^>]*?\bsrc=)([\'"])(https?://[^\'"]+?\.txt)\2', re.IGNORECASE)


def image_url(encrypted_url):
    """把源站混淆地址转成 /api/haijiao/image 的完整 URL（该端点默认开放）"""
    if not encrypted_url:
        return ''
    return f'{API_BASE}/api/haijiao/image?url={quote(encrypted_url, safe="")}'


def media_url(url):
    """源站媒体地址 → 浏览器可直接用的地址

    .txt 结尾的是混淆地址（如 xxx.jpeg.txt），必须走解密端点；
    已是普通图片地址的原样返回，免得平白多绕一层代理。
    """
    if not url:
        return ''
    return image_url(url) if url.endswith('.txt') else url


def avatar_url(node):
    """头像地址：avatar_encrypted 为真时走解密端点，否则原样返回

    适用于所有含 avatar / avatar_encrypted 的结构（帖子作者、排行榜条目、用户名片）。
    avatar_encrypted=false 的两种情形（接口已补成完整地址）：
        1. 站点默认头像 → https://…/images/common/avatar/<编号>.jpg
        2. 极少数被接口处理过的自定义头像
    """
    node = node or {}
    avatar = node.get('avatar') or ''
    if node.get('avatar_encrypted') and avatar:
        return image_url(avatar)
    return avatar


def rewrite_content_images(html_text):
    """把正文 HTML 里 <img src="混淆地址"> 的 src 替换为解密端点的完整 URL

    只改 src，其它属性原样保留（width/height/alt/style 都得过）。
    """
    if not html_text:
        return ''
    return _IMG_SRC_RE.sub(
        lambda m: f'{m.group(1)}{m.group(2)}{image_url(m.group(3))}{m.group(2)}',
        html_text,
    )
