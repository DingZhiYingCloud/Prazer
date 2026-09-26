"""图片地址标签：把第三方海报换成本站图片代理地址

用法（先在模板里 {% load xy_pic %}）：
    <img src="{% pic item.cover %}" alt="...">

好处：访客只连本站域名，图由我们本地缓存与压缩后再发（见 Web/views/pic.py）。
空值或本站 /media/ 下的图片原样返回，不做代理。
"""
from django import template

from Web.views.pic import pic_url

register = template.Library()


@register.simple_tag
def pic(url):
    return pic_url(url)
