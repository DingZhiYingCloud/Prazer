"""外链随机替换为小影 API 友情链接（运行时中间件）

开关：.env 的 FRIEND_LINK_REPLACE（on/true/1/yes 视为开启，默认关闭）。
      模块导入时读取一次，改 .env 后需重启进程才生效。

只处理：状态码 200 且 Content-Type 含 text/html 的响应。
本站域名判定：request.get_host() 去端口后小写，无需硬编码（正式环境与本地一致适用）。

替换规则（每条外链独立随机挑一条友情链接）：
    1. 只处理 <a> 标签；href 非 http(s) 的相对链接/锚点跳过；域名等于本站域名跳过；
    2. href → 替换为友情链接 url；
    3. title → 已有则替换，否则插入到 <a> 标签内（名称做 html.escape 防属性注入）；
    4. 锚文本 → 仅当链接内是**纯文本**（无 <img>/<span>/<svg> 等子标签）才替换为网站名；
       含子标签的链接保持原内容，只换 href + title。

为什么放在响应阶段改写：友情链接需要在服务端渲染进 HTML 供搜索引擎抓取，
所以不能用前端 JS 去换。
"""
import html
import os
import random
import re

from Web.services.friend_links import get_friend_links

# 开关：模块导入时读取一次
_ENABLED = os.getenv('FRIEND_LINK_REPLACE', '').lower() in ('on', 'true', '1', 'yes')

_A_TAG_RE = re.compile(r'<a\b[^>]*>.*?</a>', re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r'\bhref=(["\'])(.*?)\1', re.IGNORECASE)
_TITLE_RE = re.compile(r'\btitle=(["\'])(.*?)\1', re.IGNORECASE)


def _host_of(url):
    """取 URL 的主机名（去协议、路径与端口），用于判断是否本站链接"""
    host = url.split('//', 1)[-1].split('/', 1)[0]
    return host.split(':', 1)[0].lower()


def _replace_links_in_html(markup, links, own_host):
    """把 markup 中的外链随机替换为友情链接（返回替换后的 HTML）"""

    def replace_one(match):
        tag = match.group(0)
        href_match = _HREF_RE.search(tag)
        if not href_match:
            return tag
        href = href_match.group(2).strip()
        if not href.lower().startswith(('http://', 'https://')):
            return tag
        if _host_of(href) == own_host:
            return tag

        link = random.choice(links)
        name = html.escape(link['name'], quote=True)
        # 1) href：按匹配区间拼接替换，避免正则二次匹配误伤后面的 title 内容
        tag = tag[:href_match.start(2)] + link['url'] + tag[href_match.end(2):]
        # 2) title：已有则替换，否则插入到 <a ...> 标签头内
        title_match = _TITLE_RE.search(tag)
        if title_match:
            tag = tag[:title_match.start(2)] + name + tag[title_match.end(2):]
        else:
            head_end = tag.find('>')
            tag = tag[:head_end] + f' title="{name}"' + tag[head_end:]
        # 3) 锚文本：仅纯文本链接才替换，含子标签（图片/图标）的保持原内容
        inner_start = tag.find('>') + 1
        inner_end = tag.rfind('</a>')
        inner = tag[inner_start:inner_end]
        if inner.strip() and '<' not in inner:
            tag = tag[:inner_start] + name + tag[inner_end:]
        return tag

    return _A_TAG_RE.sub(replace_one, markup)


class FriendLinkReplaceMiddleware:
    """在响应阶段把页面里的外链随机替换为小影 API 友情链接

    开关关闭、响应非 HTML、无可用友情链接时一律原样放行。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not _ENABLED or response.status_code != 200:
            return response
        if 'text/html' not in response.get('Content-Type', ''):
            return response
        # 流式响应（如文件下载）没有完整 content，跳过
        if getattr(response, 'streaming', False):
            return response
        links = get_friend_links()
        if not links:
            return response
        try:
            markup = response.content.decode('utf-8')
        except (AttributeError, UnicodeDecodeError):
            return response
        own_host = request.get_host().split(':')[0].lower()
        response.content = _replace_links_in_html(markup, links, own_host).encode('utf-8')
        # 内容长度已变，删掉旧头让服务器重新计算
        if response.has_header('Content-Length'):
            del response['Content-Length']
        return response
