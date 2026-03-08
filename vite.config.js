import { defineConfig } from 'vite';

export default defineConfig({
    server: {
        host: '0.0.0.0',
        port: 5173,
        proxy: {
            // Proxy /graphhopper/* → GraphHopper server on the Docker host
            '/graphhopper': {
                target: 'http://host.docker.internal:8989',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/graphhopper/, ''),
            },
        },
    },
});
