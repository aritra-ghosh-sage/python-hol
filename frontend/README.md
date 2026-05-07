# Frontend

This is the Next.js 16 frontend for Python HOL.

It provides three main operator flows:

- query knowledge over `WS /ws/chat`
- ingest content through REST endpoints
- update retriever settings through REST endpoints

## Stack

- Next.js 16.2.3
- React 19
- Zustand
- Tailwind CSS v4
- Vitest

## Install

```bash
pnpm install
```

## Run

```bash
pnpm dev
```

Default app URL: `http://localhost:3000`

## Required Backend

Start the FastAPI backend separately:

```bash
cd ..
source .venv/bin/activate
uvicorn api:app --reload
```

## Environment Variables

- `NEXT_PUBLIC_API_URL`
  Defaults to `http://localhost:8000`
- `NEXT_PUBLIC_WS_URL`
  Defaults to `ws://localhost:8000/ws/chat`

## Scripts

```bash
pnpm dev
pnpm build
pnpm start
pnpm lint
pnpm test:unit
```

## What the UI Uses

REST:

- `GET /config`
- `PUT /config`
- `POST /documents`
- `GET /documents/sources`

WebSocket:

- `WS /ws/chat`

## Validate

```bash
pnpm lint
pnpm test:unit
pnpm build
```

## Notes

- Keep backend and frontend contracts aligned when editing request or response models.
- If the UI cannot connect, verify the two `NEXT_PUBLIC_*` variables first.
- For broader repo guidance, see the root `README.md` and `CLAUDE.md`.
