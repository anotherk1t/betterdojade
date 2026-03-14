import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [],
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
