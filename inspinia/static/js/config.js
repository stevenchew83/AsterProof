/**
 * Template Name: Inspinia - Admin & Dashboard Template
 * By (Author): WebAppLayers
 * Module/App (File Name): Config
 * Version: 5.1.0
 */

;(function () {
    const html = document.documentElement
    const attrMap = {
        "data-skin": "skin",
        "data-bs-theme": "theme",
        "data-menu-color": "sidenavColor",
        "data-sidenav-size": "sidenavSize",
        "data-topbar-color": "topbarColor",
        "data-layout-position": "position",
        "data-layout-width": "width",
        "dir": "dir",
        "data-sidenav-user": "sidenavUser",
    }

    const htmlConfig = {}
    Object.entries(attrMap).forEach(([attr, key]) => {
        const val = html.getAttribute(attr)
        if (val !== null) htmlConfig[key] = key === "sidenavUser" ? val === "true" : val
    })

    function readPreferences() {
        try {
            const saved = sessionStorage.getItem("__THEME_CONFIG__")
            if (saved) return JSON.parse(saved) || {}

            const legacy = JSON.parse(sessionStorage.getItem("__INSPINIA_CONFIG__") || "{}")
            const preferences = {}
            if (["light", "dark"].includes(legacy?.theme)) preferences.theme = legacy.theme
            if (["default", "condensed", "compact"].includes(legacy?.sidenav?.size)) {
                preferences.sidenavSize = legacy.sidenav.size
            }
            return preferences
        } catch {
            return {}
        }
    }

    const storedConfig = readPreferences()
    const config = Object.assign(
        {
            "dir": "ltr",
            "skin": "default",
            "theme": "light",
            "width": "fluid",
            "position": "fixed",
            "orientation": "vertical",
            "sidenavSize": "default",
            "sidenavUser": true,
            "topbarColor": "light",
            "sidenavColor": "dark",
        },
        htmlConfig,
        storedConfig,
        htmlConfig
    )

    const params = new URLSearchParams(window.location.search)
    const set = (k, v) => v && (config[k] = k === "sidenavUser" ? v === "true" : v)
    Object.values(attrMap).forEach((k) => set(k, params.get(k)))

    window.skinPresets = {
        "flat": {
            "theme": "light",
            "sidenavUser": false,
            "topbarColor": "light",
            "sidenavColor": "dark",
        },
        "luxe": {
            "theme": "light",
            "sidenavUser": true,
            "topbarColor": "dark",
            "sidenavColor": "light",
        },
        "neon": {
            "theme": "light",
            "sidenavUser": false,
            "topbarColor": "gray",
            "sidenavColor": "gray",
        },
        "saas": {
            "theme": "light",
            "sidenavUser": true,
            "topbarColor": "light",
            "sidenavColor": "dark",
        },
        "pixel": {
            "theme": "light",
            "sidenavUser": true,
            "topbarColor": "light",
            "sidenavColor": "gradient",
        },
        "retro": {
            "theme": "light",
            "sidenavUser": true,
            "topbarColor": "light",
            "sidenavColor": "gradient",
        },
        "galaxy": {
            "theme": "dark",
            "sidenavUser": true,
            "topbarColor": "dark",
            "sidenavColor": "light",
        },
        "modern": {
            "theme": "light",
            "sidenavUser": true,
            "topbarColor": "light",
            "sidenavColor": "gradient",
        },
        "default": {
            "theme": "light",
            "sidenavUser": true,
            "topbarColor": "light",
            "sidenavColor": "dark",
        },
        "minimal": {
            "theme": "light",
            "sidenavUser": false,
            "topbarColor": "light",
            "sidenavColor": "gray",
        },
        "material": {
            "theme": "light",
            "sidenavUser": true,
            "topbarColor": "dark",
            "sidenavColor": "light",
        },
    }

    const preset = window.skinPresets[config.skin] || {}

    const storedSkin = storedConfig.skin || "default"
    const savedForSkin = config.skin === storedSkin ? storedConfig : {}
    Object.assign(config, preset, savedForSkin, htmlConfig)
    Object.values(attrMap).forEach((k) => set(k, params.get(k)))

    window.defaultConfig = structuredClone(config)
    window.config = config

    const apply = (a, v) => v && html.setAttribute(a, v)
    apply("data-skin", config.skin)
    apply("data-bs-theme", config.theme === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : config.theme)
    apply("data-menu-color", config.sidenavColor)
    apply("data-topbar-color", config.topbarColor)
    apply("data-layout-width", config.width)
    apply("data-layout-position", config.position)
    apply("dir", config.dir)

    let size = config.sidenavSize
    if (window.innerWidth <= 767) size = "offcanvas"
    else if (window.innerWidth <= 1140 && size !== "offcanvas") size = "condensed"
    apply("data-sidenav-size", size)
    config.sidenavUser ? html.setAttribute("data-sidenav-user", "true") : html.removeAttribute("data-sidenav-user")
})()
