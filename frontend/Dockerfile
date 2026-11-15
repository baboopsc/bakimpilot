# ---- BakımPilot web (Next.js standalone server) ----
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# API_ORIGIN is read by next.config.ts rewrites at build time and baked into the routes manifest.
ARG API_ORIGIN=http://api:8000
ENV API_ORIGIN=$API_ORIGIN
RUN npm run build

# Final image: only the standalone server + static assets (no dev dependencies).
FROM node:24-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN adduser -D -u 10001 web
COPY --from=build --chown=web /app/.next/standalone ./
COPY --from=build --chown=web /app/.next/static ./.next/static
USER web
EXPOSE 3000
CMD ["node", "server.js"]
