/* ============ 首页 Hero：影院橱窗（PC）/ 原生横滑图集（移动） ============
 * 设计要点：
 *   1. **只有一份 DOM**（每个 .xy-hero-slide 都是一条可爬取的链接）。
 *      移动端它就是"一屏一张"的横滑图集；PC 端同一份节点既是缩略图条，
 *      左侧大图与右侧文字由 JS 按当前项更新。
 *   2. 滑动**不写手势代码**：移动端交给浏览器原生 scroll-snap，所以一定滑得动；
 *      JS 只监听滚动，把当前项同步到圆点与（PC 的）文字区。
 *   3. 自动轮播只在 PC 生效（5 秒一张，带进度条）。鼠标停在轮播上会暂停，
 *      移开继续；用户手动切换（缩略图/箭头/键盘）只是**重新计时**，轮播会接着走，
 *      不会像早期那样一被操作就永久停掉。
 */
(function () {
    'use strict';

    var AUTOPLAY_MS = 5000;
    var DESKTOP_QUERY = '(min-width: 1024px)';
    // 文字/氛围底图"淡出 → 换内容 → 淡入"的中间等待时长（信息区分条入场，最晚一条约 0.18s）
    var SWAP_DELAY_MS = 200;
    // 照片"抽卡"动画的时长，与 input.css 里 0.56s 的 xy-card-out-* 关键帧对齐
    var SLIDE_MS = 560;

    function initHero(hero) {
        var track = hero.querySelector('[data-hero-track]');
        var slides = Array.prototype.slice.call(hero.querySelectorAll('[data-hero-slide]'));
        if (!track || slides.length < 2) return;

        var backdrop = hero.querySelector('[data-hero-backdrop]');
        var noteEl = hero.querySelector('[data-hero-note]');
        var titleEl = hero.querySelector('[data-hero-title]');
        var titleLink = hero.querySelector('[data-hero-titlelink]');
        var introEl = hero.querySelector('[data-hero-intro]');
        var posterImg = hero.querySelector('[data-hero-posterimg]');
        var posterPrev = hero.querySelector('[data-hero-posterprev]');
        var posterLink = hero.querySelector('[data-hero-posterlink]');
        var ctaLink = hero.querySelector('[data-hero-cta]');
        var dotsBox = hero.querySelector('[data-hero-dots]');
        var countEl = hero.querySelector('[data-hero-count]');
        var prevBtn = hero.querySelector('[data-hero-prev]');
        var nextBtn = hero.querySelector('[data-hero-next]');

        var desktop = window.matchMedia(DESKTOP_QUERY);
        var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        var current = 0;
        var dots = [];
        var timer = null;
        var scrollTimer = null;
        var preloaded = false;
        var barOn = false;                                   // 进度条是否显示（= 允许自动轮播）
        var paused = false;                                  // 悬停 / 切后台时冻结计时与进度条
        var deadline = 0;                                    // 本轮自动切换的到期时间戳
        var remaining = AUTOPLAY_MS;                         // 暂停后剩下的毫秒数
        var swapTimer = null;                                // 文字淡出→换内容→淡入的等待计时
        var posterTimer = null;                              // 海报交叉淡入的收尾计时
        var posterFading = false;                            // 海报是否正在交叉淡入

        var scrollBehavior = function () {
            return reduceMotion ? 'auto' : 'smooth';
        };

        /* 进度条时长只在 JS 里写一次（AUTOPLAY_MS），CSS 通过 var(--xy-hero-dwell) 读取，
         * 避免 5 秒这个数字在 JS / CSS 各写一份、改一处忘一处。 */
        hero.style.setProperty('--xy-hero-dwell', (AUTOPLAY_MS / 1000) + 's');

        /* 让当前这一格的进度条从 0 重新走针：
         * 先清掉动画，读一次 offsetWidth 强制重排，再把动画挂回去 —— 否则浏览器
         * 认为动画名没变，不会重新开始。 */
        function restartTimer() {
            if (!barOn) return;
            slides.forEach(function (slide) {
                var bar = slide.querySelector('.xy-hero-timer');
                if (!bar) return;
                bar.style.animation = 'none';
                if (slide.classList.contains('is-active')) {
                    void bar.offsetWidth;
                    bar.style.animation = '';
                }
            });
        }

        /* PC 端切换时把海报直接换到大图上，若该图还在懒加载队列里，
         * 就会出现"先空一下再出现"的闪动。这里提前把 9 张海报取进缓存，
         * 切换时就是纯本地换图。移动端图集是逐屏滚动加载的，不做预取以免浪费流量。 */
        function preloadPosters() {
            if (preloaded || !desktop.matches) return;
            preloaded = true;
            slides.forEach(function (slide) {
                var cover = slide.getAttribute('data-cover');
                if (!cover) return;
                var img = new Image();
                img.src = cover;
            });
        }

        function buildDots() {
            if (!dotsBox) return;
            dotsBox.innerHTML = '';
            dots = slides.map(function (slide, index) {
                var dot = document.createElement('button');
                dot.type = 'button';
                dot.className = 'xy-hero-dot';
                dot.setAttribute('aria-label', '第 ' + (index + 1) + ' 部：' + (slide.getAttribute('data-name') || ''));
                dot.addEventListener('click', function () { takeOver(); go(index, true); });
                dotsBox.appendChild(dot);
                return dot;
            });
        }

        /* 照片"抽卡"式切换：旧图先抬起（放大 + 轻转），再缩小着被抽走；新图从另一侧滑入落位。
         *
         * 两个图层：主图层（[data-hero-posterimg]）永远放"新图"，
         * is-prev 快照层（[data-hero-posterprev]）压在上面、负责把"旧图"抽走。
         * 分三步，关键是每一步都"先定格、再动"，否则两次改样式会被浏览器合并成同一帧：
         *   1. 快照层定格成当前这张（同一张图，视觉上零变化）；
         *   2. 主图层换上新图并先摆到框外（此刻被快照层完全盖住，看不到）；
         *   3. 两层一起动 —— 旧图走关键帧动画（抬起 → 缩小抽离），新图滑入落位。
         * 动画里缩放"先放大再缩小"，缩小时新图已经铺满画面，所以不会露出底色。
         * 方向由 is-out-left / is-out-right 两个关键帧决定：往后翻往左抽，往前翻往右抽。
         *
         * 减少动态效果、首屏、同一张图时直接换，不做动画。 */
        function slidePoster(cover, name, dir) {
            if (!posterImg || !cover) return;
            var oldSrc = posterImg.getAttribute('src');
            if (!posterPrev || reduceMotion || !oldSrc || oldSrc === cover) {
                posterImg.src = cover;
                posterImg.alt = name;
                return;
            }
            if (posterFading) { settlePoster(); }   // 上一次还没滑完：先立刻收尾，再重新滑

            var forward = dir >= 0;
            var sign = forward ? 1 : -1;
            var inFrom = 'translateX(' + (102 * sign) + '%) rotate(' + (2.5 * sign) + 'deg) scale(1.05)';

            posterFading = true;
            window.clearTimeout(posterTimer);

            posterPrev.src = oldSrc;                                  // 1) 旧图定格
            posterPrev.classList.remove('is-out-left', 'is-out-right');
            freeze(posterPrev, 'translateX(0)', '1');
            void posterPrev.offsetWidth;                              // 让上一轮动画状态彻底落定
            posterPrev.classList.add(forward ? 'is-out-left' : 'is-out-right');

            posterImg.src = cover;                                    // 2) 新图就位（框外）
            posterImg.alt = name;
            freeze(posterImg, inFrom, '');

            animate(posterImg, 'translateX(0) rotate(0deg) scale(1)'); // 3) 新图滑入落位

            posterTimer = window.setTimeout(settlePoster, SLIDE_MS);
        }

        /* 收尾：把图层恢复成"随时可以再来一次"的状态（主图层归位、快照层藏到原位） */
        function settlePoster() {
            window.clearTimeout(posterTimer);
            posterFading = false;
            if (posterImg) { freeze(posterImg, 'translateX(0)', ''); }
            if (posterPrev) {
                posterPrev.classList.remove('is-out-left', 'is-out-right');
                freeze(posterPrev, 'translateX(0)', '0');
            }
        }

        /* 不带过渡地直接写值：先关过渡 → 写值 → 强制重排 → 交回过渡，
         * 这样下一步的改动才会真的"动"起来，而不是跟前一步合并到同一帧。 */
        function freeze(el, transform, opacity) {
            el.style.transition = 'none';
            el.style.transform = transform;
            el.style.opacity = opacity;
            void el.offsetWidth;
            el.style.transition = '';
        }

        function animate(el, transform) {
            el.style.transform = transform;
        }

        function updateInfo(index, instant, dir) {
            var slide = slides[index];
            if (!slide) return;
            var name = slide.getAttribute('data-name') || '';
            var cover = slide.getAttribute('data-cover') || '';
            var href = slide.getAttribute('href') || '#';

            function applyText() {
                if (noteEl) { noteEl.textContent = slide.getAttribute('data-note') || ''; }
                if (titleEl) { titleEl.textContent = name; }
                if (titleLink) { titleLink.href = href; }
                if (introEl) { introEl.textContent = slide.getAttribute('data-intro') || ''; }
                if (posterLink) { posterLink.href = href; posterLink.title = name; }
                if (ctaLink) { ctaLink.href = href; }
                if (backdrop && cover) { backdrop.style.backgroundImage = 'url("' + cover + '")'; }
            }

            // 首屏 / 移动端滚动同步 / 系统要求减少动态效果：直接换，不做推拉与淡入
            if (instant || reduceMotion) {
                hero.classList.remove('is-switching');
                if (posterImg && cover) { posterImg.src = cover; posterImg.alt = name; }
                applyText();
                return;
            }
            // 照片自己滑（不会露底），文字与氛围底图则先淡出、换完再淡入
            slidePoster(cover, name, dir || 0);
            window.clearTimeout(swapTimer);
            hero.classList.add('is-switching');
            swapTimer = window.setTimeout(function () {
                applyText();
                hero.classList.remove('is-switching');
            }, SWAP_DELAY_MS);
        }

        function mark(index) {
            slides.forEach(function (slide, i) {
                slide.classList.toggle('is-active', i === index);
            });
            dots.forEach(function (dot, i) {
                dot.classList.toggle('is-active', i === index);
            });
            // 「n / 总数」指示 + 把两侧按钮的提示文案换成"下一部是哪部"
            if (countEl) {
                countEl.textContent = (index + 1) + ' / ' + slides.length;
            }
            var prevSlide = slides[(index - 1 + slides.length) % slides.length];
            var nextSlide = slides[(index + 1) % slides.length];
            if (prevBtn && prevSlide) {
                prevBtn.title = '上一部：' + (prevSlide.getAttribute('data-name') || '');
            }
            if (nextBtn && nextSlide) {
                nextBtn.title = '下一部：' + (nextSlide.getAttribute('data-name') || '');
            }
            // 换成当前这一格后，进度条从头走针
            restartTimer();
        }

        function go(index, scroll) {
            var step = index - current;    // 用来决定照片往哪个方向抽（往后翻：新图从右边进来）
            current = ((index % slides.length) + slides.length) % slides.length;
            mark(current);
            updateInfo(current, false, step);
            // 移动端：把原生滚动容器滚到当前项；PC 端缩略图条不滚（避免列表自己跳动）
            if (scroll && !desktop.matches) {
                slides[current].scrollIntoView({
                    behavior: scrollBehavior(),
                    inline: 'center',
                    block: 'nearest'
                });
            }
        }

        /* 移动端：用户滑动后由浏览器负责滚动，我们只把"当前项"同步回来 */
        function syncFromScroll() {
            if (desktop.matches) return;
            var rect = track.getBoundingClientRect();
            var center = rect.left + rect.width / 2;
            var best = 0;
            var bestDistance = Infinity;
            slides.forEach(function (slide, index) {
                var item = slide.getBoundingClientRect();
                var distance = Math.abs(item.left + item.width / 2 - center);
                if (distance < bestDistance) { bestDistance = distance; best = index; }
            });
            if (best !== current) {
                current = best;
                mark(current);
                // 移动端文字在图里的卡片上，没有"淡出再淡入"的必要，直接同步
                updateInfo(current, true);
                // 用户自己滑过之后重新计时：别刚滑到一半就被自动轮播抢走
                rearmAuto();
            }
        }

        function stopAuto() {
            if (timer) { window.clearTimeout(timer); timer = null; }
        }

        /* ---------- 自动轮播：开关、暂停、重新计时 ----------
         * 三种状态分开处理，避免出现"进度条走完了却没换图"这类前后不一致：
         *   armed —— 当前设置下允许自动轮播（只要没开"减少动态效果"就允许，PC 与手机一致）；
         *   paused —— 鼠标停住、手指按住、或标签页切到后台：冻结计时与进度条，但**不重置**；
         *   计时用"到期时间戳"而非固定间隔，暂停后恢复能接着原来的剩余时间走，
         *   进度条的 CSS 动画也正好从冻结处继续，两边不会各走各的。
         *
         * 注意：用户手动切换（点缩略图/箭头/键盘/手机滑动）只是**重新计时**，
         * 不再像早期那样永久停掉自动轮播 —— 否则进度条会在点过之后就再也不出现。 */
        function armed() {
            return !reduceMotion;
        }

        function schedule() {
            stopAuto();
            if (!armed() || paused) return;
            deadline = Date.now() + remaining;
            timer = window.setTimeout(function () {
                remaining = AUTOPLAY_MS;
                // scroll 传 true：手机端要把原生滚动容器滚到下一张（PC 端缩略图条不滚，内部会自行忽略）
                go(current + 1, true);
                schedule();
            }, remaining);
        }

        function pauseAuto() {
            if (timer) {
                remaining = Math.max(0, deadline - Date.now());
                stopAuto();
            }
            paused = true;
            hero.classList.add('is-paused');
        }

        function resumeAuto() {
            paused = false;
            hero.classList.remove('is-paused');
            schedule();
        }

        /* 用户手动切换后调用：整轮重新计时，进度条从 0 重走，自动轮播继续 */
        function rearmAuto() {
            remaining = AUTOPLAY_MS;
            resumeAuto();
            restartTimer();
        }

        /* 允许/禁止自动轮播（初始化、断点变化时调用）：禁止时连进度条一起收起 */
        function armAuto() {
            var on = armed();
            barOn = on;
            hero.classList.toggle('is-counting', on);
            if (!on) {
                stopAuto();
                paused = false;
                hero.classList.remove('is-paused');
                return;
            }
            schedule();
            restartTimer();
        }

        /* ---------- 事件绑定 ---------- */
        track.addEventListener('scroll', function () {
            window.clearTimeout(scrollTimer);
            scrollTimer = window.setTimeout(syncFromScroll, 80);
        }, { passive: true });

        // PC：点缩略图 = 切换当前项（点"已经是当前项"的那张则放行，直接进详情页）
        track.addEventListener('click', function (event) {
            if (!desktop.matches) return;   // 移动端：点卡片直接进详情
            var target = event.target;
            var slide = target && target.closest ? target.closest('[data-hero-slide]') : null;
            if (!slide) return;
            var index = slides.indexOf(slide);
            if (index === current) return;
            event.preventDefault();
            go(index, false);
            rearmAuto();
        }, true);

        if (prevBtn) {
            prevBtn.addEventListener('click', function () { go(current - 1, true); rearmAuto(); });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', function () { go(current + 1, true); rearmAuto(); });
        }

        // 键盘：焦点在 Hero 内时左右键切换（不劫持输入框）
        hero.addEventListener('keydown', function (event) {
            var tag = (event.target && event.target.tagName) || '';
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            if (event.key === 'ArrowLeft') { go(current - 1, true); rearmAuto(); }
            else if (event.key === 'ArrowRight') { go(current + 1, true); rearmAuto(); }
        });

        hero.addEventListener('mouseenter', pauseAuto);
        // mouseover 会随着指针在 hero 内部移动反复触发：手动点击后我们把暂停解除了，
        // 只要指针一动就会立刻重新冻住（不用先移出再移入才恢复悬停暂停）
        hero.addEventListener('mouseover', pauseAuto);
        hero.addEventListener('mouseleave', resumeAuto);
        hero.addEventListener('focusin', pauseAuto);
        hero.addEventListener('focusout', resumeAuto);
        // 手机端：手指按住画面时停住（别在人家滑动/看图时自己换），松手后重新计时
        hero.addEventListener('touchstart', pauseAuto, { passive: true });
        hero.addEventListener('touchend', rearmAuto, { passive: true });
        hero.addEventListener('touchcancel', rearmAuto, { passive: true });
        document.addEventListener('visibilitychange', function () {
            // 切到后台时进度条的 CSS 动画仍在空转，回来时整轮重来，避免"回到前台就立刻换图"
            if (document.hidden) { pauseAuto(); } else { rearmAuto(); }
        });

        if (desktop.addEventListener) {
            desktop.addEventListener('change', function () {
                // 断点切换后把滚动位置与自动轮播重新对齐一次
                preloadPosters();
                go(current, true);
                armAuto();
            });
        }

        buildDots();
        mark(0);
        updateInfo(0, true);   // 首屏直接显示，不做淡入
        preloadPosters();
        armAuto();
    }

    document.addEventListener('DOMContentLoaded', function () {
        var heroes = document.querySelectorAll('[data-hero]');
        for (var i = 0; i < heroes.length; i++) { initHero(heroes[i]); }
    });
})();
