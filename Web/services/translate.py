"""动态内容翻译（本地人工词表 + 缓存 + 回退原文）

接口返回的帖子标题 / 板块 / 分类都是**中文源**，属于"动态数据"。本站的做法是：
**一次性把要展示的数据翻好**（清单见下），渲染时直接取，不再依赖任何外部翻译服务。

    PROVIDER = 'local'（默认）：读 locale/<语言>/hardcoded.json 里的**人工词表**。
        {"中文原文": "译文", …} —— 由人工/一次性整理，静态数据用它最省事、最稳。
    PROVIDER = ''：关闭翻译，全部回落中文原文。
    其它取值：预留给以后接 DeepL / Google 等（实现 _provider_translate 即可）。

翻译结果按「语言 + 原文」缓存（30 天），同一段文本只查一次词表；词表里没有的
文本**原样返回中文**，绝不影响页面渲染。

用法：
    from Web.services import translate

    translate.translate(['标题A', '标题B'], 'pt-br')   # 批量
    translate.translate_text('板块名')                  # 单个（用当前语言）
"""
import hashlib
import json
import logging
import os
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.utils.translation import get_language

logger = logging.getLogger(__name__)

# 翻译后端：'local' = 本地人工词表（默认）；'' = 关闭；其它 = 预留外部服务
PROVIDER = (os.getenv('TRANSLATE_PROVIDER') or 'local').strip().lower()
API_KEY = os.getenv('TRANSLATE_API_KEY') or ''

# 源语言（接口内容是中文）
SOURCE_LANG = 'zh'
# 项目语言代码 → 翻译服务/目录用的语言代码
LANG_MAP = {'pt-br': 'pt-BR', 'zh-hans': 'zh'}
# 本地词表按语言放哪个 locale 目录
LOCAL_LOCALE_DIRS = {'pt-br': 'pt_BR', 'zh-hans': 'zh_Hans'}
LOCAL_FILE_NAME = 'hardcoded.json'

CACHE_PREFIX = 'xyapi:i18n'
CACHE_TTL = 30 * 24 * 3600

# 词表按语言缓存到进程内，避免每次请求都读盘
_local_tables = {}


def _local_table(target_lang):
    """读本地人工词表：{中文原文: 译文}；读不到就返回空表（等于不翻译）"""
    if target_lang in _local_tables:
        return _local_tables[target_lang]

    table = {}
    locale_dir = LOCAL_LOCALE_DIRS.get(target_lang)
    if locale_dir:
        path = Path(settings.BASE_DIR) / 'locale' / locale_dir / LOCAL_FILE_NAME
        try:
            if path.exists():
                with path.open('r', encoding='utf-8') as fp:
                    data = json.load(fp)
                if isinstance(data, dict):
                    table = data
        except Exception:
            logger.exception('本地词表读取失败：%s', path)
    _local_tables[target_lang] = table
    return table


def is_enabled(target_lang):
    """是否需要（且能够）翻译：目标就是中文、或后端关闭时返回 False"""
    if LANG_MAP.get(target_lang) in (None, 'zh'):
        return False
    if PROVIDER == 'local':
        return True
    return bool(PROVIDER and API_KEY)


def _cache_key(target_lang, text):
    digest = hashlib.sha1(text.encode('utf-8')).hexdigest()
    return f'{CACHE_PREFIX}:{target_lang}:{digest}'


def _provider_translate(texts, target_lang):
    """具体翻译后端：返回与入参等长的列表；词表没命中的位置给空串（调用方回退原文）"""
    if PROVIDER == 'local':
        table = _local_table(target_lang)
        return [table.get(text) or '' for text in texts]
    return None


def translate(texts, target_lang):
    """批量翻译（返回与输入等长的列表）

    关闭翻译、词表没命中、后端异常时，对应位置原样返回原文。
    """
    texts = list(texts or [])
    if not texts or not is_enabled(target_lang):
        return texts

    result = [None] * len(texts)
    pending = {}
    for index, text in enumerate(texts):
        if not text:
            result[index] = text
            continue
        cached = cache.get(_cache_key(target_lang, text))
        if cached is not None:
            result[index] = cached
        else:
            result[index] = text  # 先占位，下面翻不出来就保持原文
            pending[index] = text

    if pending:
        try:
            translated = _provider_translate(list(pending.values()), target_lang)
        except Exception:
            logger.exception('动态内容翻译失败，回退原文')
            translated = None
        if translated and len(translated) == len(pending):
            for (index, source), output in zip(pending.items(), translated):
                if output:
                    result[index] = output
                    cache.set(_cache_key(target_lang, source), output, CACHE_TTL)
    return result


def translate_text(text, target_lang=None):
    """单个文本翻译（语言默认取当前请求语言）；空值原样返回"""
    if not text:
        return text
    target_lang = target_lang or get_language()
    return translate([text], target_lang)[0]
