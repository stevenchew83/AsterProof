# Theme web fonts

Original Google Fonts WOFF2 files used by the existing Inspinia theme families, served locally to remove external CSS imports from the rendering path. Font styles, weight ranges, unicode ranges and `font-display: swap` are unchanged. Browsers request only the font faces used by the current skin and text. No build-time or runtime network fetch is needed.

Each family retains its SIL Open Font License in `OFL.txt`. `provenance.json` records source CSS URLs, original font URLs, byte sizes and SHA-256 hashes. Declarations live in `scss/config/_fonts.scss`; rebuild assets with `npm run build` after changes.
