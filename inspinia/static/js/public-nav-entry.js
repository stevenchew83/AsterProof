import "bootstrap/js/dist/collapse";
import "bootstrap/js/dist/dropdown";

const themeToggle = document.getElementById("theme-toggle");
const root = document.documentElement;
const themeKey = "asterproof-public-theme";

function setTheme(theme) {
    root.dataset.bsTheme = theme;
    themeToggle.setAttribute("aria-pressed", String(theme === "dark"));
}

if (themeToggle) {
    try {
        setTheme(localStorage.getItem(themeKey) === "dark" ? "dark" : "light");
    } catch {
        setTheme("light");
    }
    themeToggle.hidden = false;
    themeToggle.addEventListener("click", () => {
        const theme = root.dataset.bsTheme === "dark" ? "light" : "dark";
        setTheme(theme);
        try {
            localStorage.setItem(themeKey, theme);
        } catch {
            // The theme still works when storage is unavailable.
        }
    });
}
