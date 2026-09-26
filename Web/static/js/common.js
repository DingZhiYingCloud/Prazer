/* ============ 全站公共脚本 ============
 * 说明：本文件会作为 Tailwind 的扫描源之一（见 input.css 的 @source），
 *       因为 menu-active / toast / xy-to-top 这些类名是 JS 运行时才挂上的，
 *       只靠模板扫描 Tailwind 不会生成对应样式。
 */

// 轻量提示（搜索关键词为空等场景）：警示样式 + 警示图标，"蓝色信息条"不像提示
function bzToast(msg) {
    var box = document.getElementById('bz-toast');
    if (!box) {
        box = document.createElement('div');
        box.id = 'bz-toast';
        box.className = 'toast toast-top toast-end z-[9999] mt-20';
        document.body.appendChild(box);
    }
    var item = document.createElement('div');
    item.className = 'alert alert-warning shadow-lg text-sm';
    item.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4 shrink-0" aria-hidden="true">' +
        '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>' +
        '<path d="M12 9v4"/><path d="M12 17h.01"/></svg>';
    var text = document.createElement('span');
    text.textContent = msg;
    item.appendChild(text);
    box.appendChild(item);
    setTimeout(function () { item.remove(); }, 2400);
}

// 站内搜索：统一跳转 /so/<关键词>.html（关键词需 URL 编码）
function bzSearch(form) {
    var kw = (form.wd.value || '').replace(/^\s+|\s+$/g, '');
    if (!kw) { bzToast('请输入要搜索的内容'); return false; }
    window.location.href = '/so/' + encodeURIComponent(kw) + '.html';
    return false;
}

// 点击弹层外部时收起 <details> 弹层（保留给"更多/筛选"这类原生弹层用）
document.addEventListener('click', function (e) {
    var openList = document.querySelectorAll('details[open]');
    for (var i = 0; i < openList.length; i++) {
        // 点在弹层内部（含 summary 本身）就不管，交给原生行为切换
        if (!openList[i].contains(e.target)) openList[i].removeAttribute('open');
    }
});

// 按当前 URL 给侧边栏导航打高亮
// data-nav 写的是目标地址的**完整路径**（如 /list/124.html），这里做整串比较。
// 早期用「前缀匹配」，导致 /list/1.html 的前缀命中 /list/124.html，
// 于是「福利」页面里「电影」也被点亮 —— 改用整串比较后不会再串。
document.addEventListener('DOMContentLoaded', function () {
    var path = window.location.pathname;
    var nodes = document.querySelectorAll('[data-nav]');
    for (var i = 0; i < nodes.length; i++) {
        if (path === (nodes[i].getAttribute('data-nav') || '')) {
            nodes[i].classList.add('menu-active');
        }
    }
});

/* ============ 搜索结果关键词高亮 ============
 * 关键词放在页面的 [data-hl-source] 上（服务端输出），标题节点标 [data-hl]。
 * 只替换"纯文本"内容：先做 HTML 转义再匹配，避免片名里的 & < > 破坏结构。
 */
document.addEventListener('DOMContentLoaded', function () {
    var source = document.querySelector('[data-hl-source]');
    var keyword = source ? (source.getAttribute('data-hl-source') || '') : '';
    if (!keyword) return;

    function escapeHtml(text) {
        return text.replace(/[&<>]/g, function (ch) {
            return ch === '&' ? '&amp;' : (ch === '<' ? '&lt;' : '&gt;');
        });
    }

    // 先转义（与待匹配文本同一套编码），再转义正则元字符
    var needle = escapeHtml(keyword).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (!needle) return;
    var re = new RegExp(needle, 'gi');

    var nodes = document.querySelectorAll('[data-hl]');
    for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var escaped = escapeHtml(el.textContent || '');
        re.lastIndex = 0;
        if (!re.test(escaped)) continue;
        re.lastIndex = 0;
        el.innerHTML = escaped.replace(re, function (match) {
            return '<mark class="rounded bg-warning/40 px-0.5 text-inherit">' + match + '</mark>';
        });
    }
});

/* ============ 主题切换（浅色 / 深色） ============
 * 主题本身由 template.html 的首屏脚本决定（本地记忆 → 否则跟随系统），
 * 这里只负责点击切换 + 记忆 + 过渡。
 * 图标由 CSS 按 [data-theme] 显示（见 input.css）。
 *
 * 过渡：daisyUI 的主题是一堆 CSS 变量，直接切换会"啪"地一下整页变色。
 * 这里在切换的瞬间给 <html> 临时挂 .xy-theme-fading，让配色类属性走 0.28s 过渡，
 * 过渡结束立刻摘掉 —— 不常驻，避免影响卡片悬停等其它交互，
 * 也保证首屏（内联脚本定主题那一次）不会"闪一下过渡"。
 */
document.addEventListener('DOMContentLoaded', function () {
    var btn = document.querySelector('[data-theme-toggle]');
    if (!btn) return;
    var fadeTimer = null;
    btn.addEventListener('click', function () {
        var root = document.documentElement;
        var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (!reduceMotion) {
            root.classList.add('xy-theme-fading');
            if (fadeTimer) window.clearTimeout(fadeTimer);
            fadeTimer = window.setTimeout(function () {
                root.classList.remove('xy-theme-fading');
                fadeTimer = null;
            }, 320);
        }
        root.setAttribute('data-theme', next);
        try { localStorage.setItem('xy_theme', next); } catch (e) { /* 隐私模式忽略 */ }
    });
});

/* ============ 图片：加载失败兜底 ============
 * load / error 不冒泡，所以在捕获阶段监听：
 *   加载失败 → 换成兜底图（media/placeholder.png），并标记避免兜底图自身失败时死循环。
 * 不做淡入/骨架：图片加载完成直接显示（用户明确要求页面零动画）。
 */
document.addEventListener('DOMContentLoaded', function () {
    var FALLBACK = '/media/placeholder.png';

    document.addEventListener('error', function (event) {
        var el = event.target;
        if (!el || el.tagName !== 'IMG' || el.dataset.fallbackApplied) return;
        el.dataset.fallbackApplied = '1';
        el.src = FALLBACK;
    }, true);
});

/* ============ 回到顶部 ============
 * 滚动一段距离后淡入；尊重系统「减少动态效果」设置，不做平滑滚动。
 */
document.addEventListener('DOMContentLoaded', function () {
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'xy-to-top btn btn-primary btn-circle btn-sm shadow-lg';
    btn.setAttribute('aria-label', '回到顶部');
    btn.title = '回到顶部';
    btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4">' +
        '<path d="m18 15-6-6-6 6"/></svg>';
    btn.addEventListener('click', function () {
        window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
    });
    document.body.appendChild(btn);

    function update() {
        btn.classList.toggle('is-visible', window.scrollY > 400);
    }
    window.addEventListener('scroll', update, { passive: true });
    update();
});

/* ============ 顶部进度条：切换页面 / 提交搜索时的等待反馈 ============
 * 服务端渲染站点，点链接后要等新文档返回，这段时间页面毫无反馈。
 * 这里在点链接 / 提交表单时拉出顶部进度条，新页面一渲染出来它就没了。
 * 真进度拿不到，所以是"先快后慢推进到 ~92%"的假进度（见 input.css 的动画）。
 *
 * 只做等待反馈，绝不拦截导航：所有判断不通过的情况一律直接放行。
 */
(function () {
    var bar = document.createElement('div');
    bar.className = 'xy-progress';
    bar.setAttribute('aria-hidden', 'true');
    bar.innerHTML = '<i class="xy-progress-fill"></i>';
    document.body.appendChild(bar);
    var fill = bar.firstChild;
    var running = false;
    var guard = null;

    function start() {
        if (running) return;
        running = true;
        bar.classList.add('is-active');
        fill.classList.add('is-running');
        // 兜底：点了链接但导航没发生（被脚本拦掉、或浏览器放弃跳转）时别一直挂着
        if (guard) window.clearTimeout(guard);
        guard = window.setTimeout(stop, 20000);
    }

    function stop() {
        if (guard) {
            window.clearTimeout(guard);
            guard = null;
        }
        if (!running) return;
        running = false;
        bar.classList.remove('is-active');
        fill.classList.remove('is-running');
    }

    document.addEventListener('click', function (e) {
        // 只认"普通左键点击链接"：组合键、中键、_blank、下载、锚点
        // 以及 javascript:/mailto:/tel: 都不会发起整页导航，一律不显示
        if (e.defaultPrevented || e.button !== 0) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        var link = e.target.closest && e.target.closest('a');
        if (!link) return;
        if (link.target === '_blank' || link.hasAttribute('download')) return;
        var href = link.getAttribute('href') || '';
        if (!href || href.charAt(0) === '#') return;
        if (/^(javascript|mailto|tel):/i.test(href)) return;
        start();
    }, true);

    document.addEventListener('submit', function (e) {
        if (e.defaultPrevented) return;
        start();
    }, true);

    // 浏览器后退/前进命中 bfcache 时，把可能残留的进度条收掉
    window.addEventListener('pageshow', function (e) {
        if (e.persisted) stop();
    });
})();
