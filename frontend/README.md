# Hybrid RAG Frontend

Next.js 16 + React 19 web interface for the Hybrid RAG document retrieval system.

**Project Version:** 0.1.0  
**Status:** 🟡 BETA — Internal development use

## 🎯 Overview

The frontend provides a modern chat interface for querying the Hybrid RAG backend. Features include:

- **Real-time chat** via WebSocket with status and results messages
- **Configuration management** for retrieval parameters
- **Document ingestion** (text, URL, file upload)
- **Source browsing** to explore document sources
- **Responsive design** with Tailwind CSS v4

## 🏗️ Project Structure

```
frontend/
├── src/
│   ├── app/                    # Next.js App Router pages
│   │   ├── layout.tsx          # Root layout (theme, providers)
│   │   ├── page.tsx            # Home page
│   │   ├── chat/               # Chat feature pages
│   │   ├── settings/           # Configuration pages
│   │   └── sources/            # Document source browser
│   ├── components/             # Feature-based components
│   │   ├── chat/               # Chat UI components
│   │   ├── data/               # Data management UI
│   │   ├── layout/             # Page structure
│   │   ├── providers/          # Context providers
│   │   ├── settings/           # Configuration UI
│   │   └── ui/                 # Reusable UI elements
│   ├── hooks/                  # Custom React hooks
│   │   ├── useApi.ts           # REST API client hook
│   │   ├── useWebSocket.ts     # WebSocket management
│   │   └── useSettings.ts      # Settings state hook
│   ├── lib/                    # Utilities and integrations
│   │   ├── api.ts              # REST API client
│   │   ├── types.ts            # TypeScript types (mirroring backend)
│   │   ├── ws.ts               # WebSocket client
│   │   ├── store.ts            # Zustand state stores
│   │   └── utils.ts            # Utility functions
│   ├── styles/                 # Global styles
│   │   └── globals.css         # Tailwind directives + custom CSS
│   └── public/                 # Static assets
│       └── favicon.ico
├── AGENTS.md                   # AI agent compatibility guide
├── CLAUDE.md                   # Claude-specific development notes
├── SETUP.md                    # Setup and environment configuration
├── next.config.ts              # Next.js configuration
├── tailwind.config.ts          # Tailwind CSS configuration
├── tsconfig.json               # TypeScript configuration
├── vitest.config.ts            # Unit test configuration
├── playwright.config.ts        # E2E test configuration
└── package.json
```

## 🚀 Quick Start

### Prerequisites
- **Node.js:** 18+
- **Package Manager:** pnpm recommended
- **Backend:** Running at `http://localhost:8000`

### Installation

```bash
# Install dependencies
pnpm install

# Configure environment
cp .env.local.example .env.local
# Edit .env.local with your API URL
```

### Development

```bash
# Start development server (http://localhost:3000)
pnpm dev

# Run type checking
pnpm tsc --noEmit

# Run linting
pnpm lint

# Run unit tests
pnpm test:unit

# Run E2E tests
pnpm test:e2e
```

### Production Build

```bash
# Build for production
pnpm build

# Start production server
pnpm start
```

## 📡 API Integration

### REST API Client

The `frontend/src/lib/api.ts` module provides a typed REST client:

```typescript
import { apiClient } from '@/lib/api';

// Health check
const health = await apiClient.healthCheck();

// Retrieve documents
const response = await apiClient.retrieve({
  query: "How do I share offline maps?",
  enable_rerank: true
});

// Get configuration
const config = await apiClient.getConfig();

// Update configuration
await apiClient.updateConfig({
  semantic_weight: 0.8,
  keyword_weight: 0.2
});

// Add documents
await apiClient.addDocuments({
  source_type: "text",
  content: "Document text...",
  source_label: "Custom Source"
});

// List document sources
const sources = await apiClient.getDocumentSources();
```

### WebSocket Client

The `frontend/src/lib/ws.ts` module provides WebSocket connectivity:

```typescript
import { ChatWebSocket } from '@/lib/ws';

const ws = new ChatWebSocket('ws://localhost:8000/ws/chat');

// Connect
await ws.connect();

// Send query and listen for responses
ws.on('status', (msg) => console.log('Status:', msg.message));
ws.on('results', (msg) => console.log('Results:', msg.results));
ws.on('error', (msg) => console.error('Error:', msg.message));

await ws.query("offline maps", true);

// Disconnect
ws.close();
```

## 🎨 Styling

The project uses **Tailwind CSS v4** with:
- **@tailwindcss/postcss** - CSS framework
- **@tailwindcss/typography** - Rich text styling
- **Dark mode support** via CSS variables
- **Responsive design** with mobile-first approach

### Global Styles

CSS directives in `src/styles/globals.css`:
```css
@import "tailwindcss";

@layer components {
  .card { @apply bg-white dark:bg-gray-900 rounded-lg shadow; }
  .btn-primary { @apply px-4 py-2 bg-blue-600 text-white rounded; }
}
```

## 📦 State Management

**Zustand** stores for application state:

```typescript
import { useStore } from '@/lib/store';

// Access state
const { messages, config } = useStore();

// Update state
useStore.setState({ messages: [...] });

// Subscribe to changes
useStore.subscribe(
  (state) => state.messages,
  (messages) => console.log('Messages updated:', messages)
);
```

## 🔐 Type Safety

**TypeScript types** in `frontend/src/lib/types.ts` mirror Pydantic models from the backend. These types are the source of truth for API contracts:

```typescript
// These types match backend Pydantic models
interface DocumentResult {
  id: string;
  text: string;
  source: string;
  score: number;
}

interface RetrievalRequest {
  query: string;
  enable_rerank?: boolean;
}

interface RetrievalResponse {
  query: string;
  results: DocumentResult[];
  total_results: number;
}
```

**See [API_INTEGRATION.md](../docs/API_INTEGRATION.md) for the canonical backend contract documentation.**

## 🧪 Testing

### Unit Tests (Vitest)

```bash
pnpm test:unit

# With coverage
pnpm test:unit -- --coverage
```

**Test files:** `*.test.ts` or `*.test.tsx`

Example:
```typescript
import { describe, it, expect } from 'vitest';
import { apiClient } from '@/lib/api';

describe('API Client', () => {
  it('should fetch health status', async () => {
    const health = await apiClient.healthCheck();
    expect(health.status).toBe('ok');
  });
});
```

### E2E Tests (Playwright)

```bash
pnpm test:e2e

# With UI
pnpm test:e2e -- --ui

# Debug mode
pnpm test:e2e -- --debug
```

**Test files:** `e2e/*.spec.ts`

Example:
```typescript
import { test, expect } from '@playwright/test';

test('chat interaction flow', async ({ page }) => {
  await page.goto('http://localhost:3000/chat');
  
  const input = page.locator('input[placeholder*="Search"]');
  await input.fill('offline maps');
  await input.press('Enter');
  
  const results = page.locator('[data-testid="results"]');
  await expect(results).toContainText('offline');
});
```

## 🌐 Environment Configuration

Create `.env.local`:

```bash
# API Configuration
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000

# Feature Flags (optional)
NEXT_PUBLIC_FEATURE_ADVANCED_CONFIG=false
```

**See [SETUP.md](./SETUP.md) for detailed environment setup.**

## 🔄 State Architecture

### Global State (Zustand)

```typescript
// Chat messages
const messages = useStore((state) => state.messages);
useStore.setState({ 
  messages: [...messages, newMessage] 
});

// Configuration
const config = useStore((state) => state.config);
useStore.setState({ config: updatedConfig });

// Settings
const settings = useStore((state) => state.settings);
useStore.setState({ settings: { ...settings, theme: 'dark' } });
```

### Component State (React.useState)

Used for local UI state (input values, loading states, modals).

## 🚨 Error Handling

All API errors are caught and displayed to users:

```typescript
try {
  const results = await apiClient.retrieve({ query });
  // Success: display results
} catch (error) {
  if (error.message.includes('RETRIEVER_NOT_READY')) {
    // Show: "Service is initializing..."
  } else if (error.message.includes('VALIDATION_ERROR')) {
    // Show: "Invalid query. Please try again."
  } else {
    // Show: "An error occurred. Please try again later."
  }
}
```

## 📊 Component Hierarchy

```
<RootLayout>
  <Providers>
    <Navigation />
    <main>
      {children}
    </main>
    <Footer />
  </Providers>
</RootLayout>
```

**Feature Routes:**
- `/` — Home
- `/chat` — Real-time chat interface
- `/settings` — Configuration management
- `/sources` — Document source browser

## 🔗 API Documentation

For complete API documentation, see:
- [API Integration](../docs/API_INTEGRATION.md) — All REST and WebSocket endpoints
- [frontend/src/lib/types.ts](../frontend/src/lib/types.ts) — Frontend-side type definitions

## ⚠️ Known Limitations

- **Authentication:** Not implemented (v0.2 feature)
- **Rate limiting:** Not enforced (TODO)
- **Mobile responsiveness:** Core features work, some polish needed

## 📝 Development Guidelines

### Code Style
- Use TypeScript strict mode
- Props should be typed explicitly
- Avoid `any` types
- Use semantic HTML for accessibility

### File Naming
- Components: `PascalCase.tsx`
- Utilities: `camelCase.ts`
- Styles: `kebab-case.css`

### Commit Messages
Follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `test:` Test updates
- `chore:` Dependency/config updates

## 🐛 Troubleshooting

### WebSocket connection fails
- Check backend is running: `curl http://localhost:8000/health`
- Verify `NEXT_PUBLIC_WS_URL` environment variable
- Check browser console for CORS errors

### State not updating
- Verify Zustand subscription is correct
- Check React DevTools for component re-renders
- Use `useShallow` for object comparisons in selectors

### Build fails
- Run `pnpm tsc --noEmit` to check TypeScript errors
- Clear `.next` directory: `rm -rf .next`
- Reinstall dependencies: `pnpm install`

## 📚 See Also

- [Hybrid RAG Library](../docs/LIBRARY_DESIGN.md) — Backend library architecture
- [Next.js 16 Breaking Changes](./AGENTS.md) — API differences from Next.js 13/14
- [Claude Development Notes](./CLAUDE.md) — Claude-specific patterns
- [Deployment Guide](../docs/DEPLOYMENT_PRODUCTION.md) — Production deployment

## 📄 License

Part of the Hybrid RAG project. See root [README.md](../README.md).
