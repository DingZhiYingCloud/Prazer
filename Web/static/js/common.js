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

/* ============ 语言切换（页脚下拉框） ============
 * 页脚的 <select name="language"> 一变就提交到 Django 的 /i18n/setlang/，
 * 由它写入语言 cookie 并把当前页翻译成对应语言前缀（见 common_html/footer.html）。
 * 只作用于挂了 data-language-switch 的表单，其它表单不受影响。
 */
document.addEventListener('DOMContentLoaded', function () {
    var forms = document.querySelectorAll('[data-language-switch]');
    for (var i = 0; i < forms.length; i++) {
        var select = forms[i].querySelector('select[name="language"]');
        if (!select) continue;
        select.addEventListener('change', function () {
            this.form.submit();
        });
    }
});

/* ============ App 下载弹窗 ============
 * 本站详情需在 App 内观看：点帖子卡片（movie_card 上的 [data-app-download] 链接）或页头
 * 「下载 App」按钮时，不跳转，改为弹出下载弹窗（#xy-app-download，见
 * common_html/app_download_modal.html）。弹窗里按平台列出入口，全部指向本地 /download。
 * 只在页面上确实存在该弹窗时才挂监听，其它页面零开销。
 */
document.addEventListener('DOMContentLoaded', function () {
    var dialog = document.getElementById('xy-app-download');
    if (!dialog || typeof dialog.showModal !== 'function') return;
    document.addEventListener('click', function (event) {
        var trigger = event.target.closest ? event.target.closest('[data-app-download]') : null;
        if (!trigger) return;
        // 组合键 / 中键 / 右键仍交给浏览器（不改默认行为），便于需要时打开原地址
        if (event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        dialog.showModal();
    });
});

/* ============ 图片：加载失败兜底 ============
 * load / error 不冒泡，所以在捕获阶段监听：
 *   加载失败 → 换成兜底图，并标记避免兜底图自身失败时死循环。
 * 兜底图是分语言的（pt-BR / zh-Hans 各一张），地址由服务端渲染在 <html data-img-placeholder>，
 * 这里读它而不是写死路径，免得中文页挂出葡语占位图。
 * 不做淡入/骨架：图片加载完成直接显示（用户明确要求页面零动画）。
 */
document.addEventListener('DOMContentLoaded', function () {
    var FALLBACK = document.documentElement.getAttribute('data-img-placeholder')
        || '/media/placeholder.png';

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

/* ============ 图片放大（帖子正文） ============
 * 只对挂了 [data-zoom-group] 的容器生效（目前是海角社区帖子正文），
 * 其它页面既不建 DOM 也不挂监听，零开销。
 *
 * 交互：点图片打开全屏查看层；「上一张 / 下一张」首尾循环；Esc 或点图片外空白关闭。
 * 键盘：图片可 Tab 聚焦，回车/空格打开。
 * 与站内其它交互一致：不做入场动画，点开即出现（样式见 input.css 的 #xy-lightbox）。
 */
document.addEventListener('DOMContentLoaded', function () {
    var groups = document.querySelectorAll('[data-zoom-group]');
    var images = [];
    for (var g = 0; g < groups.length; g++) {
        var found = groups[g].querySelectorAll('img');
        for (var i = 0; i < found.length; i++) images.push(found[i]);
    }
    if (!images.length) return;

    var box = null;
    var stage = null;
    var picture = null;
    var counter = null;
    var actions = null;
    var current = 0;
    var opener = null;

    var ICON = 'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4"';

    function build() {
        box = document.createElement('div');
        box.id = 'xy-lightbox';
        box.hidden = true;
        box.setAttribute('role', 'dialog');
        box.setAttribute('aria-modal', 'true');
        box.setAttribute('aria-label', '图片查看');
        box.innerHTML =
            '<div class="xy-lb-bar">' +
                '<span class="xy-lb-count text-sm text-base-content/70"></span>' +
                '<button type="button" class="btn btn-ghost btn-sm btn-circle" data-lb="close" aria-label="关闭">' +
                    '<svg ' + ICON + '><path d="M18 6 6 18M6 6l12 12"/></svg>' +
                '</button>' +
            '</div>' +
            '<div class="xy-lb-stage"><img class="xy-lb-img" alt="" /></div>' +
            '<div class="xy-lb-actions">' +
                '<button type="button" class="btn btn-sm" data-lb="prev">' +
                    '<svg ' + ICON + '><path d="m15 18-6-6 6-6"/></svg>上一张</button>' +
                '<button type="button" class="btn btn-sm" data-lb="next">下一张' +
                    '<svg ' + ICON + '><path d="m9 18 6-6-6-6"/></svg></button>' +
            '</div>';
        document.body.appendChild(box);

        stage = box.querySelector('.xy-lb-stage');
        picture = box.querySelector('.xy-lb-img');
        counter = box.querySelector('.xy-lb-count');
        actions = box.querySelector('.xy-lb-actions');
        box.addEventListener('click', onClick);
    }

    function show(index) {
        // 取模实现首尾循环：最后一张点"下一张"回到第一张
        current = (index + images.length) % images.length;
        picture.src = images[current].src;
        picture.alt = images[current].alt || '';
        counter.textContent = (current + 1) + ' / ' + images.length;
        actions.hidden = images.length < 2;
    }

    function open(index, trigger) {
        if (!box) build();
        opener = trigger || null;
        show(index);
        box.hidden = false;
        document.body.style.overflow = 'hidden';
        var closeBtn = box.querySelector('[data-lb="close"]');
        if (closeBtn) closeBtn.focus();
    }

    function close() {
        box.hidden = true;
        document.body.style.overflow = '';
        if (opener && opener.focus) opener.focus();
    }

    function onClick(event) {
        var btn = event.target.closest ? event.target.closest('[data-lb]') : null;
        if (!btn) {
            // 点图片本身不关，点图片外的舞台空白才关
            if (event.target === stage) close();
            return;
        }
        var action = btn.getAttribute('data-lb');
        if (action === 'close') close();
        else if (action === 'prev') show(current - 1);
        else if (action === 'next') show(current + 1);
    }

    document.addEventListener('keydown', function (event) {
        if (!box || box.hidden) return;
        if (event.key === 'Escape') close();
        else if (event.key === 'ArrowLeft') show(current - 1);
        else if (event.key === 'ArrowRight') show(current + 1);
    });

    for (var k = 0; k < images.length; k++) {
        (function (img, index) {
            img.setAttribute('tabindex', '0');
            img.addEventListener('click', function () { open(index, img); });
            img.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    open(index, img);
                }
            });
        })(images[k], k);
    }
});

/* ============ 操作结果提示自动移除 ============
 * 海角社区的写操作（签到 / 点赞 / 关注 / 打赏）走 POST-Redirect-GET，落地页会带一条提示
 * （服务端渲染的 #xy-messages）。这里几秒后把它摘掉，免得长期遮住右上角内容。
 * 与 bzToast 一致：直接移除，不做淡出动画。
 */
document.addEventListener('DOMContentLoaded', function () {
    var box = document.getElementById('xy-messages');
    if (!box) return;
    window.setTimeout(function () { box.remove(); }, 4000);
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
        if (link.hasAttribute('data-app-download')) return; // 弹下载弹窗，不发起导航
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
