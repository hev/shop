# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS deps
WORKDIR /app
# The "Similar to your browsing" rail imports the hev layer TypeScript client
# (`hevlayer`), an unpublished package vendored in-tree at app/vendor/hevlayer
# (file:vendor/hevlayer; refresh with scripts/sync-ts-client.sh). It's vendored
# rather than injected from the sibling checkout because npm bakes the file:
# link's relative path into the lockfile, and an out-of-tree ../../ link escapes
# the image's filesystem root from /app; an in-tree link is portable. npm 11
# matches the lockfile generator (node:22-alpine ships npm 10).
COPY package.json package-lock.json ./
COPY vendor ./vendor
RUN npm install -g npm@11 && npm ci

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# `next build` bundles the hevlayer client into the route handler (webpack
# inlines it; the runner stage needs no node_modules/hevlayer).
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
USER nextjs

COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
