import { defineConfig } from 'vite';

import { cloudflare } from "@cloudflare/vite-plugin";

export default defineConfig({
    plugins: [cloudflare()],
    server: {
        host: '0.0.0.0',
        port: 5173,
        proxy: {
            // Proxy /graphhopper/* → GraphHopper server on the Docker host
            '/graphhopper': {
                target: 'http://localhost:8989',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/graphhopper/, ''),
            },
        },
    },
});