# Neethi AI — Frontend

Next.js 16 (App Router) + React 19 frontend for the Neethi AI Indian Legal Domain system.

## Stack

| Technology | Version | Purpose |
|---|---|---|
| Next.js | 16.1.6 | React framework (App Router + SSR) |
| React | 19.2.3 | UI library |
| TypeScript | 5.9.3 | Type safety |
| Tailwind CSS | 4.x | Styling |
| Zustand | 4.5.x | Global state management |
| @crayonai/react-core | 0.7.7 | AI chat UI components |
| @thesysai/genui-sdk | 0.8.5 | Thesys visual explanations |
| axios | 1.x | HTTP client |

## Getting Started

```bash
# Install dependencies
npm install --legacy-peer-deps
# Note: --legacy-peer-deps is required due to @crayonai packages pinning
# tailwind-merge@^2, zustand@^4, zod@^3 as peer deps

# Development server (port 3000)
npm run dev

# Production build
npm run build
npm run start
```

Open [http://localhost:3000](http://localhost:3000)

## Pages

| Route | Description |
|---|---|
| `/` | Landing page |
| `/login` | Login form (JWT auth) |
| `/register` | User registration (role selection) |
| `/dashboard` | Main dashboard (role-aware) |
| `/query` | Legal query interface with SSE streaming |
| `/cases` | Case law search & IRAC analysis |
| `/documents/draft` | Legal document drafting (10 templates) |
| `/documents/analyze` | Document upload & analysis |
| `/statutes` | Acts & sections browser |
| `/resources` | Nearby legal resources (SerpAPI) |
| `/history` | Query history |
| `/profile` | User profile |
| `/settings` | User settings |
| `/admin` | Admin dashboard |
| `/admin/users` | User management |
| `/admin/activity` | Activity logs |

## Backend Proxy

All `/api/v1/...` requests are proxied to the backend via `next.config.ts`:

```
Browser → Next.js :3000 → /api/v1/* rewrite → FastAPI :8000
```

Set `BACKEND_URL` in `.env.local` for custom backend URL (default: `http://localhost:8000`).

## Environment Variables

Create `.env.local` in `frontend/`:

```env
BACKEND_URL=http://localhost:8000    # Backend API URL (server-side only)
THESYS_API_KEY=<your-thesys-key>    # Thesys visual SDK
```

## Project Structure

```
src/
├── app/
│   ├── (auth)/             # Login, Register
│   ├── (dashboard)/        # All dashboard pages
│   └── api/                # Next.js API routes (Thesys proxy, doc stream)
├── components/
│   ├── layout/             # Header, Sidebar
│   ├── ui/                 # Badge, Button, Card, Input
│   └── providers/          # ThemeProvider
├── lib/
│   ├── api.ts              # Axios HTTP client (points to /api/v1)
│   ├── i18n.ts             # Internationalization helpers
│   └── utils.ts            # cn() utility (clsx + tailwind-merge)
├── store/
│   ├── auth.ts             # Auth state (Zustand + persist)
│   └── ui.ts               # UI state (Zustand + persist)
└── types/
    └── index.ts            # TypeScript type definitions
```
