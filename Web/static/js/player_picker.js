/* ============ 线路 + 选集面板（详情页与播放页共用） ============
 * 面板由服务端渲染好，这里只做三件"增强"：
 *   1. 线路切换：详情页点线路 → 切换该线路的选集面板（不跳转，纯浏览）；
 *   2. 选集整理：集数多时按每 50 集分档（只显示当前档），并可一键正序/倒序；
 *   3. 播放页额外：把「上一集 / 下一集」按钮指向正确的相邻集。
 *
 * 为什么播放页的线路是链接而不是切换按钮：换源意味着换一条流，
 * 必须重新加载播放器；做成链接（跳到该线路第 1 集）语义更直白，也不会出现
 * "线路高亮了但画面还是旧线路"的错位。
 *
 * 注意：这里**不做**键盘切集。早先绑定过 ←/→ 跳上一集/下一集，会和播放器自身
 * 的 ←/→（快退/快进 10 秒）抢按键，用户反馈不需要，已移除。
 */
(function () {
    'use strict';

    var GROUP_SIZE = 50;   // 每档集数：超过这个数量才出现分档按钮

    /* 返回该面板"按集数升序"的选集节点数组（后续排序/定位都以它为准，避免被 DOM 顺序带偏） */
    function setupPanel(panel) {
        var grid = panel.querySelector('[data-episode-grid]');
        if (!grid) return [];
        var episodes = Array.prototype.slice.call(grid.children);
        if (!episodes.length) return [];

        var rangeBox = panel.querySelector('[data-range-btns]');
        var toggle = panel.querySelector('[data-order-toggle]');
        var label = panel.querySelector('[data-order-label]');

        var reversed = false;
        var group = 0;

        // 播放页：默认定位到"当前正在播的那一集"所在档（模板给当前集加了 btn-primary）
        for (var i = 0; i < episodes.length; i++) {
            if (episodes[i].classList.contains('btn-primary')) {
                group = Math.floor(i / GROUP_SIZE);
                break;
            }
        }

        function render() {
            var total = episodes.length;
            var pages = Math.max(1, Math.ceil(total / GROUP_SIZE));
            if (group > pages - 1) { group = pages - 1; }
            if (group < 0) { group = 0; }

            // 档位始终按**集数区间**划分（1-50 / 51-100…），标签与实际集数严格对应；
            // 倒序时把档位按钮顺序与档内顺序一起反过来，方便先看最新几集。
            if (rangeBox) {
                rangeBox.innerHTML = '';
                if (pages > 1) {
                    var indexes = [];
                    for (var p = 0; p < pages; p++) { indexes.push(p); }
                    if (reversed) { indexes.reverse(); }
                    indexes.forEach(function (p) {
                        var from = p * GROUP_SIZE + 1;
                        var to = Math.min(total, (p + 1) * GROUP_SIZE);
                        var btn = document.createElement('button');
                        btn.type = 'button';
                        btn.className = 'btn btn-xs ' + (p === group ? 'btn-primary' : 'btn-ghost');
                        btn.textContent = from + '-' + to;
                        btn.addEventListener('click', function () { group = p; render(); });
                        rangeBox.appendChild(btn);
                    });
                }
            }

            // 当前档排到最前（按需倒序）并显示；其余留在 DOM 末尾但隐藏 ——
            // 全部集数始终在 HTML 里，不依赖脚本也能被爬虫与无 JS 用户读到。
            var slice = episodes.slice(group * GROUP_SIZE, (group + 1) * GROUP_SIZE);
            if (reversed) { slice.reverse(); }
            slice.forEach(function (el) {
                el.style.display = '';
                grid.appendChild(el);
            });
            episodes.forEach(function (el) {
                if (slice.indexOf(el) === -1) {
                    el.style.display = 'none';
                    grid.appendChild(el);
                }
            });

            if (label) { label.textContent = reversed ? '倒序' : '正序'; }
        }

        if (toggle) {
            toggle.addEventListener('click', function () {
                reversed = !reversed;
                render();
            });
        }

        render();
        return episodes;
    }

    /* 播放页：把「上一集 / 下一集」按钮指向相邻集
     * 以传入的"升序数组"定位当前集，因此不受分档/倒序后的 DOM 顺序影响。 */
    function setupEpisodeNav(picker, panel, ascending) {
        if (!ascending || !ascending.length) return;
        var index = -1;
        for (var i = 0; i < ascending.length; i++) {
            if (ascending[i].classList.contains('btn-primary')) { index = i; break; }
        }
        if (index < 0) return;

        var prev = ascending[index - 1];
        var next = ascending[index + 1];
        var prevBtn = picker.querySelector('[data-episode-prev]');
        var nextBtn = picker.querySelector('[data-episode-next]');

        if (prevBtn && prev) {
            prevBtn.href = prev.href;
            prevBtn.title = '上一集：' + prev.textContent.trim();
            prevBtn.classList.remove('hidden');
        }
        if (nextBtn && next) {
            nextBtn.href = next.href;
            nextBtn.title = '下一集：' + next.textContent.trim();
            nextBtn.classList.remove('hidden');
        }
    }

    function initPicker(picker) {
        var panels = Array.prototype.slice.call(picker.querySelectorAll('[data-source-panel]'));
        if (!panels.length) return;

        // 当前面板：模板已给当前线路去掉 hidden
        var currentIndex = 0;
        for (var i = 0; i < panels.length; i++) {
            if (!panels[i].hidden) { currentIndex = i; break; }
        }
        panels[currentIndex].hidden = false;

        // 线路栏：只有一条线路时没有存在意义（省下一列横向空间）。
        // 注意按**线路条目数**判断 —— 播放页的线路是 <a>，没有 data-source-btn，
        // 早先按 data-source-btn 计数会让播放页的线路栏被误隐藏。
        var rail = picker.querySelector('[data-source-rail]');
        if (rail && rail.children.length < 2) { rail.classList.add('hidden'); }

        var episodesByPanel = panels.map(setupPanel);

        var sourceBtns = Array.prototype.slice.call(picker.querySelectorAll('[data-source-btn]'));
        sourceBtns.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var sid = btn.getAttribute('data-source-btn');
                panels.forEach(function (panel) {
                    panel.hidden = panel.getAttribute('data-source-panel') !== sid;
                });
                sourceBtns.forEach(function (other) {
                    var on = other.getAttribute('data-source-btn') === sid;
                    other.classList.toggle('btn-primary', on);
                    other.classList.toggle('btn-ghost', !on);
                    other.setAttribute('aria-pressed', on ? 'true' : 'false');
                });
            });
        });

        if (picker.getAttribute('data-episode-nav') === '1') {
            setupEpisodeNav(picker, panels[currentIndex], episodesByPanel[currentIndex]);
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var pickers = document.querySelectorAll('[data-picker]');
        for (var i = 0; i < pickers.length; i++) { initPicker(pickers[i]); }
    });
})();
