// Dev-server proxy (frontend/docs/decisions.md D3): the browser calls /api on its own origin (http://localhost:4200)
// and the dev server forwards it to the gateway. No path rewrite: the gateway strips /api itself.
// The dev server runs in Docker, so the gateway on the host is reached through host.docker.internal
// (see extra_hosts in compose.yaml). Override with GATEWAY_URL.
//
// changeOrigin changes only the Host header. The Origin header from the browser (http://localhost:4200) is passed
// through untouched, which auth-svc needs on /auth/refresh and /auth/logout (CORS_ALLOWED_ORIGINS).
export default {
  '/api': {
    target: process.env.GATEWAY_URL ?? 'http://host.docker.internal:8080',
    changeOrigin: true,
    secure: false,
    logLevel: 'warn',
  },
};
