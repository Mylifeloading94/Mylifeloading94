# IRL

Be a person, not a feed.

IRL is an authenticity-first social network: a chronological (never algorithmic)
feed, no public like counts, a daily BeReal-style dual-camera "Moment" that
unlocks once you post your own, Close Friends circles, and location check-ins
verified by the browser's real GPS rather than typed in by hand.

## Stack

- Next.js 16 (App Router, Turbopack) + TypeScript + Tailwind CSS v4
- Auth.js (NextAuth v5) with credentials (username/email + password) auth, JWT sessions
- Prisma + SQLite — zero external services required
- Local filesystem media storage (`public/uploads`)

## Getting started

```bash
npm install
npx prisma migrate dev   # creates prisma/dev.db
npx prisma db seed       # optional: demo users + posts
npm run dev
```

Visit http://localhost:3000. If you ran the seed script, log in as any of
`alex`, `mia`, `noah`, `priya`, `zeke`, `sam` with password `password123`.

## Features

- Accounts, profiles (avatar, name, bio), follow/unfollow
- Chronological home feed (following + yourself only — no ranking algorithm)
- Posts with photos, captions, optional verified location tag
- Likes with no public vanity-metric count (only the author sees a total;
  everyone else just sees a few liker avatars) and comments
- Close Friends circles — restrict a post to a hand-picked subset of people
- 24-hour ephemeral Stories with a tap-through viewer
- **Moment**: once a day, capture a back-camera + front-camera photo pair;
  everyone else's Moments for the day stay blurred until you post your own
- Notifications for follows, likes, and comments
- Direct messages (1:1) with lightweight polling for near-real-time delivery
- Light/dark theme

## Known limitations

This is a fully working single-server app, not a drop-in replacement for
Instagram's infrastructure: media is stored on local disk (fine for a demo
or small deployment, not for CDN-scale traffic), there's no push
notification service, and messaging/notifications use polling rather than
WebSockets. All of that is swappable (S3-compatible storage, a real-time
transport, a managed Postgres instance) without changing the product logic.
