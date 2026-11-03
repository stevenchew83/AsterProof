/* Progressive enhancement for the read-only student explorer. */
(function (global) {
    'use strict';

    // Invalidating at schedule time also guards the debounce window. Aborting alone
    // is insufficient: a response may already be resolving when the input changes.
    function createRequests(options) {
        let version = 0, timer = null, controller = null, lastURL = null;
        const delay = options.delay === undefined ? 250 : options.delay;
        const schedule = options.setTimeout || global.setTimeout.bind(global);
        const unschedule = options.clearTimeout || global.clearTimeout.bind(global);
        function run(url, debounce) {
            lastURL = url;
            const ticket = ++version;
            if (timer !== null) unschedule(timer);
            if (controller) controller.abort();
            options.pending();
            async function execute() {
                timer = null;
                controller = new AbortController();
                try {
                    const response = await options.fetch(url, {signal: controller.signal, credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'text/html'}});
                    if (ticket !== version) return;
                    if (response.redirected || response.status === 401 || response.status === 403) {
                        options.navigate(response.url || url);
                        return;
                    }
                    if (!response.ok) throw new Error('refresh failed');
                    const html = await response.text();
                    if (ticket !== version) return;
                    options.success(html, url);
                } catch (error) {
                    if (ticket === version && error.name !== 'AbortError') options.failure();
                } finally {
                    if (ticket === version) options.settled();
                }
            }
            if (debounce) timer = schedule(execute, delay);
            else execute();
        }
        return {run, retry: () => { if (lastURL) run(lastURL, false); }, cancel: () => {
            version++;
            if (timer !== null) unschedule(timer);
            if (controller) controller.abort();
        }};
    }

    function filterURL(action, values) {
        const url = new URL(action);
        url.search = '';
        url.hash = '';
        ['q', 'year', 'type', 'discipline', 'evidence'].forEach(key => {
            const value = values[key] || '';
            if (value && !(key === 'type' && value === 'achievements')) url.searchParams.set(key, value);
        });
        return url.href;
    }

    function filterValues(href) {
        const url = new URL(href);
        return Object.fromEntries(['q', 'year', 'type', 'discipline', 'evidence'].map(name =>
            [name, url.searchParams.get(name) || (name === 'type' ? 'achievements' : '')]));
    }

    function mount(root) {
        if (!global.fetch || !global.AbortController || !global.DOMParser) return;
        const form = root.querySelector('[data-student-filters]');
        const feedback = root.querySelector('[data-student-feedback]');
        const loading = root.querySelector('[data-student-loading]');
        const retry = root.querySelector('[data-student-retry]');
        const reset = root.querySelector('[data-student-reset]');
        const state = loading.parentElement;
        const fields = ['q', 'year', 'type', 'discipline', 'evidence'];
        let displayedSearch = global.location.search;
        function results() { return root.querySelector('[data-student-results]'); }
        function openTarget(hash, focus) {
            // Only local, existing IDs; never interpret source text as markup/selectors.
            const id = hash.slice(1);
            const target = document.getElementById(id);
            if (!target || !root.contains(target)) return;
            for (let node = target; node && node !== root; node = node.parentElement) {
                if (node.tagName === 'DETAILS') node.open = true;
            }
            if (focus) {
                (target.querySelector('summary') || target).focus({preventScroll: true});
                target.scrollIntoView({block: 'nearest'});
            }
        }
        const requests = createRequests({
            fetch: global.fetch.bind(global),
            navigate: url => global.location.assign(url),
            pending: () => {
                loading.hidden = false; feedback.textContent = ''; retry.hidden = true;
                state.classList.remove('is-error'); results().setAttribute('aria-busy', 'true');
            },
            settled: () => { loading.hidden = true; results().setAttribute('aria-busy', 'false'); },
            failure: () => {
                feedback.textContent = 'Results could not be refreshed. The previous results are still shown.';
                state.classList.add('is-error'); retry.hidden = false;
            },
            success: (html, requestedURL) => {
                const incoming = new DOMParser().parseFromString(html, 'text/html');
                const page = incoming.querySelector('[data-student-detail]');
                if (!page) { global.location.assign(requestedURL); return; }
                if (page.dataset.studentId !== root.dataset.studentId) throw new Error('Unexpected student');
                const selectors = ['[data-student-results]', '[data-student-header]', '[data-student-timeline]', '[data-student-secondary]', '[data-student-navigation]', '[data-student-highlights]', '[data-student-charts]'];
                const replacements = selectors.map(selector => [root.querySelector(selector), page.querySelector(selector)]);
                if (replacements.some(pair => !pair[0] || !pair[1])) throw new Error('Incomplete page');
                const canonical = new URL(page.querySelector('[data-student-results]').dataset.canonicalUrl, global.location.href);
                if (canonical.origin !== global.location.origin || canonical.pathname !== global.location.pathname) throw new Error('Unexpected route');
                const openIDs = Array.from(root.querySelectorAll('details[open][id]')).map(el => el.id);
                const focusWasResults = results().contains(document.activeElement);
                const focusedView = document.activeElement && document.activeElement.dataset.studentView;
                const focusedChart = document.activeElement && document.activeElement.dataset.studentChartFilter;
                replacements.forEach(([old, next]) => old.replaceWith(next));
                root.querySelector('[data-student-view-title]').textContent = page.querySelector('[data-student-view-title]').textContent;
                fields.forEach(name => {
                    const old = form.elements.namedItem(name), next = page.querySelector('[data-student-filters]').elements.namedItem(name);
                    if (name === 'type') old.value = next.value;
                    ['aria-invalid', 'aria-describedby'].forEach(attr => {
                        if (next.hasAttribute(attr)) old.setAttribute(attr, next.getAttribute(attr));
                        else old.removeAttribute(attr);
                    });
                });
                reset.hidden = page.querySelector('[data-student-reset]').hidden;
                openIDs.forEach(id => {
                    const detail = document.getElementById(id);
                    if (detail && root.contains(detail)) detail.open = true;
                });
                global.history.replaceState(null, '', canonical.href);
                displayedSearch = canonical.search;
                const valid = results().dataset.filtersValid === 'true';
                feedback.textContent = valid ? results().dataset.matchCount + ' matching records.' : 'Check the filter errors below.';
                if (focusWasResults) {
                    const region = results().querySelector('[role="region"]');
                    if (region) region.focus();
                    else { feedback.tabIndex = -1; feedback.focus(); }
                } else if (focusedView) {
                    const view = Array.from(root.querySelectorAll('[data-student-view]')).find(link => link.dataset.studentView === focusedView);
                    if (view) view.focus();
                } else if (focusedChart) {
                    const link = Array.from(root.querySelectorAll('[data-student-chart-filter]')).find(item => item.dataset.studentChartFilter === focusedChart);
                    (link || root.querySelector('#student-charts-title')).focus({preventScroll: true});
                }
            }
        });
        function apply(debounce) {
            const values = Object.fromEntries(fields.map(name => [name, form.elements.namedItem(name).value]));
            requests.run(filterURL(form.action, values), debounce);
        }
        form.addEventListener('submit', event => { event.preventDefault(); apply(false); });
        form.elements.namedItem('q').addEventListener('input', event => { if (!event.isComposing) apply(true); });
        form.elements.namedItem('q').addEventListener('compositionend', () => apply(true));
        ['year', 'type', 'discipline', 'evidence'].forEach(name => form.elements.namedItem(name).addEventListener('change', () => apply(false)));
        retry.addEventListener('click', () => requests.retry());
        root.addEventListener('click', event => {
            const link = event.target.closest('a');
            if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            if (link.matches('.student-record-link')) {
                openTarget(link.hash, true);
            } else if (link.matches('[data-student-chart-filter]')) {
                event.preventDefault();
                const url = new URL(link.href);
                const values = filterValues(url.href);
                fields.forEach(name => { form.elements.namedItem(name).value = values[name]; });
                requests.run(url.href, false);
            } else if (link.matches('[data-student-view]')) {
                event.preventDefault();
                form.elements.namedItem('type').value = link.dataset.studentView;
                apply(false);
            } else if (link.matches('[data-student-reset]')) {
                event.preventDefault();
                fields.filter(name => name !== 'type').forEach(name => { form.elements.namedItem(name).value = ''; });
                apply(false);
            } else if (link.closest('[data-student-results] nav')) {
                event.preventDefault(); requests.run(link.href, false);
            }
        });
        global.addEventListener('popstate', () => {
            const url = new URL(global.location.href);
            if (url.search === displayedSearch) {
                openTarget(url.hash, true);
                return;
            }
            const values = filterValues(url.href);
            fields.forEach(name => { form.elements.namedItem(name).value = values[name]; });
            requests.run(url.href, false);
        });
        global.addEventListener('pagehide', () => requests.cancel());
        global.addEventListener('hashchange', () => openTarget(global.location.hash, true));
        root.classList.add('is-enhanced');
        openTarget(global.location.hash, false);
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = {createRequests, filterURL, filterValues, mount};
    if (typeof document !== 'undefined') document.querySelectorAll('[data-student-detail]').forEach(mount);
})(typeof window !== 'undefined' ? window : globalThis);
