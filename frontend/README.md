# BakımPilot frontend

Next.js 16 (App Router, TypeScript) + TanStack Query + Tailwind CSS 4.

```bash
npm install
npm run dev          # http://localhost:3000, proxies /api/* to Django on :8000 (API_ORIGIN)
npm test             # Vitest unit tests
npm run typecheck
npm run e2e          # Playwright end-to-end (needs the backend running + `seed_demo`)
```

For E2E, start the backend with a relaxed login throttle (the suite logs in many times):
`LOGIN_THROTTLE=1000/min python manage.py runserver`.

Visual review: `SCREENSHOTS=1 npx playwright test screenshots` writes every page to `./screenshots/`.
