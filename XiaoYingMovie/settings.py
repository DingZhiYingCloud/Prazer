import os
from pathlib import Path
from dotenv import load_dotenv

# 读取 .env 作为配置来源。
# override=True：让 .env 里的值**覆盖**同名的已存在环境变量。
# 默认行为（override=False）是"环境变量优先"，于是 shell / IDE 注入的同名变量会静默盖掉 .env，
# 出现"明明改了 .env 却不生效"的现象。本项目把 .env 当作唯一配置入口
# （见 .env 里"切线上/本地只改这一处"），所以要让它说了算。
# 代价：.env 里出现过的键，环境变量就再也盖不动它 —— 部署时别再用系统环境变量配这些项，
# 并确保服务器的 .env 没留着开发期的值（尤其是 DEBUG）。
load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key-change-in-production')

DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

# 只列出本机，避免忘配 .env 时把网站直接暴露给任意 Host（线上在 .env 里写真实域名）
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')

# 关闭 COOP：这里要传 Python 的 None（Django 检测到假值就不下发该响应头）。
# 早期写的是字符串 "None"，会被当成字面值输出成 `Cross-Origin-Opener-Policy: None` ——
# 非法值，浏览器直接忽略，等于这个设置根本没生效。
SECURE_CROSS_ORIGIN_OPENER_POLICY = None

# 反向代理（Nginx / IIS）终止 HTTPS 时，让 Django 依据 X-Forwarded-Proto 判定真实协议。
# 不加这一条，线上 HTTPS 站点在 robots.txt 的 Sitemap 地址、页面的 canonical 与 og:url
# 里都会输出 http://，搜索引擎会把两者当成不同 URL（见 README「部署教程」第 7 步）。
# 前提：应用只监听回环地址，外部无法绕过反代直接伪造该请求头。
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'API.apps.ApiConfig',
    'Web.apps.WebConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # GZip：首页 HTML 约 130KB、output.css 约 80KB，压缩后大约只剩 1/6。
    # 放在最前面，让后面中间件（尤其改写 HTML 的友情链接中间件）的产物都被压到。
    'django.middleware.gzip.GZipMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    # 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'Web.middleware.FriendLinkReplaceMiddleware', # 外链随机替换为小影 API 友情链接（FRIEND_LINK_REPLACE=on 时生效）
]

ROOT_URLCONF = 'XiaoYingMovie.urls' # 此处应该成您的项目名

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'Web.services.site_info.site_info', # 站点名称/联系方式（取自 .env，改名只改 .env）
                'Web.services.movie_nav.nav_categories', # 页头分类导航（小影电影分类接口，带缓存）
                'Web.services.friend_links.friend_links', # 小影 API 友情链接（后端拉取+1小时缓存，渲染进 HTML 供搜索引擎可见）
            ],
        },
    },
]

WSGI_APPLICATION = 'XiaoYingMovie.wsgi.application' # 此处应该成您的项目名


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

# SQLite 数据库(请求守卫日志/规则存储,由 migrate 自动建表)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'zh-hans' # 中文简体

TIME_ZONE = 'Asia/Shanghai' # 上海时间

USE_I18N = True # 开启国际化

USE_TZ = True # 开启时区支持


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'
# 静态源目录：全站静态资源都放这里（output.css / js / images）。
# 开发与生产都直接从该目录对外服务，不走 collectstatic（见 XiaoYingMovie/urls.py 的两条分支）。
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'Web', 'static')]
# collectstatic 的收集目标：刻意与源目录分开，否则"收集"就是把文件复制到自己身上
# （Django 也会直接报 staticfiles.E002）。本项目不依赖 collectstatic，保留它是为了
# 需要时能把静态文件集中交给 Nginx / CDN。
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')


# 默认主键字段类型配置
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 媒体文件配置
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


# ============ 站点品牌与联系方式（二开改名只需改 .env） ============
# 站点主名称：用于 logo、SEO 标题、结构化数据等全站展示
SITE_NAME = os.getenv('SITE_NAME', '小影影视')
# 站点副名称：与主名称并列出现在 SEO 文案中（留空则模板只用主名称）
SITE_NAME_ALT = os.getenv('SITE_NAME_ALT', '小影电影')
# SEO 描述里的品牌组合短语：优先取 .env 的 SITE_BRAND，未配置时自动按「副名（主名）」拼接
SITE_BRAND = os.getenv('SITE_BRAND') or (f'{SITE_NAME_ALT}（{SITE_NAME}）' if SITE_NAME_ALT else SITE_NAME)
# 页脚免责声明的联系邮箱（写 # 代替 @ 可防爬虫，展示时说明即可）
SITE_CONTACT_EMAIL = os.getenv('SITE_CONTACT_EMAIL', 'contact#example.com')
# 联系方式（页脚「联系我们」弹窗用）
SITE_CONTACT_WECHAT = os.getenv('SITE_CONTACT_WECHAT', '')
SITE_CONTACT_TG = os.getenv('SITE_CONTACT_TG', '')


# ============ 问题反馈中心（小影统一反馈系统，子项目零代码接入）============
# 反馈页托管在小影 API 侧：{XIAOYING_API_BASE}/feedback/<APPID>/。
# APPID 直接用签名那套的 XIAOYING_API_APPID（见 API/common/signature.py）——
# 反馈数据按「接入项目」归属，和签名用的是同一个项目，不需要再单独配一个。
# 本站没有登录体系，用户以游客身份匿名提交；有登录态的项目可再换一次性票据带上身份。
# 详见 Web/services/feedback.py 顶部的接入说明。


# ============ 缓存配置（小影 API 数据缓存，只缓存不落库） ============
# 说明：影片数据统一缓存到本地文件（零依赖，不写数据库）。
# 命中缓存直接返回，未命中才请求小影 API，避免每个访客都回源。
# 清缓存：删除项目根目录下的 cache 目录
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': os.path.join(BASE_DIR, 'cache'),
        'OPTIONS': {
            # 缓存文件数上限。Django 默认仅 300，而 FileBasedCache 每写一个键都会检查
            # 这个上限，超了就随机删掉 1/3 —— 本站按分类/详情/播放等维度生成大量键，
            # 用默认值会让缓存互相挤掉、命中率塌陷、回源次数暴涨。
            'MAX_ENTRIES': 20000,
            # 满了以后每次淘汰 1/4（默认 3 = 淘汰 1/3），淘汰得温和一些。
            'CULL_FREQUENCY': 4,
        },
    },
    # 海角社区登录态专用缓存（见 SESSION_ENGINE）。
    # 必须与上面的接口结果缓存分开：结果是"满了随机淘汰 1/4"，共用的话
    # 某次缓存爆量会把访客的登录态一起淘汰掉（表现为莫名其妙掉登录）。
    'sessions': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': os.path.join(BASE_DIR, 'cache', 'sessions'),
        'OPTIONS': {
            'MAX_ENTRIES': 20000,
            'CULL_FREQUENCY': 4,
        },
    },
}

# ============ 海角社区登录态 ============
# 只服务 /haijiao/ 频道（站内其它频道没有登录概念，不受影响）。
# 会话存服务端（cache session），浏览器只拿 sessionid，
# 海角 token 不会出现在用户 cookie 里；也不落库（本站对海角账号只做转交，不存密码、不建模型）。
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'sessions'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14      # 两周
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'             # 跨站表单 POST 不带 cookie（CSRF 兜底，见 MIDDLEWARE 说明）

# ============ 小影电影接口缓存时长 ============
# 数据类（分类/首页/列表/详情）缓存较久，播放地址（m3u8 带时效）较短，
# 与接口文档说明一致；时长可在 .env 调整，0 表示不缓存。
XIAOYING_MOVIE_CACHE_TTL = int(os.getenv('XIAOYING_MOVIE_CACHE_HOURS', '6')) * 3600
XIAOYING_MOVIE_PLAY_CACHE_TTL = int(os.getenv('XIAOYING_MOVIE_PLAY_CACHE_MINUTES', '30')) * 60
XIAOYING_MOVIE_SEARCH_CACHE_TTL = int(os.getenv('XIAOYING_MOVIE_SEARCH_CACHE_MINUTES', '30')) * 60

