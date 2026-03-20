module.exports = [
    {
        vendorsJS: [
            "./node_modules/jquery/dist/jquery.min.js",
            "./node_modules/bootstrap/dist/js/bootstrap.bundle.min.js",
            "./node_modules/lucide/dist/umd/lucide.min.js",
            "./node_modules/simplebar/dist/simplebar.min.js",
        ],

        vendorCSS: [
            "./node_modules/@tabler/icons-webfont/dist/tabler-icons.min.css",
        ],

        vendorFonts: [
            "./node_modules/@tabler/icons-webfont/dist/fonts/tabler-icons.woff2",
            "./node_modules/@tabler/icons-webfont/dist/fonts/tabler-icons.woff",
            "./node_modules/@tabler/icons-webfont/dist/fonts/tabler-icons.ttf",
        ],
    },
    {
        name: "apexcharts",
        assets: ["./node_modules/apexcharts/dist/apexcharts.min.js"],
    },
    {
        name: "datatables",
        assets: [
            "./node_modules/datatables.net/js/dataTables.min.js",
            "./node_modules/datatables.net-bs5/js/dataTables.bootstrap5.min.js",
            "./node_modules/datatables.net-bs5/css/dataTables.bootstrap5.min.css",
        ],
    },
];
