(() => {
    const root = document.documentElement;
    const dark = window.matchMedia("(prefers-color-scheme: dark)");

    function applyTheme() {
        const mode = root.dataset.theme;
        root.dataset.bsTheme = mode === "dark" || (mode === "auto" && dark.matches) ? "dark" : "light";
    }

    root.dataset.skin = "default";
    applyTheme();
    new MutationObserver(applyTheme).observe(root, {attributes: true, attributeFilter: ["data-theme"]});
    dark.addEventListener("change", applyTheme);
})();
