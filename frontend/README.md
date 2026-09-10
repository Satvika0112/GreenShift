# GreenShift Enterprise React Control Plane

The GreenShift Enterprise Control Plane is a high-performance React 19 + TypeScript + Vite Single Page Application (SPA) providing real-time multi-region carbon-aware Kubernetes scheduling governance, team isolation, audit chain verification, and fleet impact analytics.

---

## Architecture & Proxy Topology

### 1. Development Topology
```
[Browser Client]
       │ (http://localhost:3000)
       ▼
[Vite Dev Server Proxy]
       │ (/api, /auth, /live, /health, /metrics)
       ▼
[FastAPI Backend (http://127.0.0.1:8000)]
```
- **Same-Origin Requests**: In development, `VITE_API_BASE_URL` is kept empty (`""`). The browser sends requests to relative endpoints (`/api/...`, `/auth/...`).
- **Vite Proxy**: `vite.config.ts` transparently proxies API and health endpoints to the backend on `http://127.0.0.1:8000`.
- **Zero CORS Issues**: Because client requests are same-origin (`http://localhost:3000`), no browser CORS preflight blocks the dev workflow.

### 2. Production Topology (Docker / Kubernetes)
```
[Browser Client]
       │ (http://<host>:3000 or port 80)
       ▼
[Nginx Reverse Proxy & Static Asset Server]
       ├── /api/    ──► http://api:8000/api/
       ├── /auth/   ──► http://api:8000/auth/
       ├── /health  ──► http://api:8000/health
       ├── /metrics ──► http://api:8000/metrics
       └── /        ──► try_files $uri $uri/ /index.html (SPA Fallback)
```
- **SPA Routing**: Nginx serves the compiled production bundle from `/usr/share/nginx/html` and falls back all nested routes to `/index.html`, eliminating 404s on browser refresh.
- **Upstream Proxy**: Nginx proxies API calls directly to the backend service container `api:8000`.

---

## Local Development Setup

### Prerequisites
- Node.js 20+ (Node 22 recommended)
- Python 3.10+ (for FastAPI backend)

### Steps
1. **Configure Environment**:
   ```bash
   cp .env.example .env
   ```
   *Keep `VITE_API_BASE_URL=` empty for local development.*

2. **Install Dependencies**:
   ```bash
   npm install
   ```

3. **Start the Frontend**:
   ```bash
   npm run dev
   ```
   Application will be available at `http://localhost:3000`.

4. **Run Unit Tests**:
   ```bash
   npm test
   ```

5. **Typecheck & Production Build**:
   ```bash
   npm run build
   ```

---

## Environment Configuration

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | *(empty)* | Base URL for API requests. Keep empty for Vite/Nginx proxy. |

---

## Accessibility & Security Standards

- **Semantic HTML & ARIA**: Semantic elements (`<nav>`, `<aside>`, `<main>`, `<dialog>`) with standard ARIA labels on navigation and interactive toggles.
- **Keyboard Navigation**: Escape key dismisses mobile drawer navigation, notification popover, and governance modals.
- **Backend-Authoritative RBAC**: Frontend role-checks are UI-advisory only; all operations are strictly verified by backend JWT Bearer tokens.
