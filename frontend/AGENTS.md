<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# TypeScript & Next.js Coding Standards

## Code Quality & Type Safety

### TypeScript Configuration
- **Strict mode enabled**: All type checking rules enforced (`strict: true`)
- **No implicit `any`**: Every variable, parameter, and return value must have explicit types
- **ESNext features**: Use modern ES2017+ syntax
- **Path aliases**: Use `@/` prefix for imports from `src/` directory

### Type Safety Requirements
- **Explicit typing**: Never rely on type inference for function signatures
- **Type guards**: Validate external data (API responses, user input) at boundaries
- **Zod validation**: Use Zod schemas for runtime validation at API boundaries
- **Generic types**: Use for reusable components and utilities
  ```typescript
  // GOOD: Explicit types
  interface ButtonProps {
    variant: "primary" | "secondary" | "ghost";
    size: "sm" | "md" | "lg";
    onClick: (event: React.MouseEvent<HTMLButtonElement>) => void;
    children: React.ReactNode;
  }

  // BAD: Implicit any
  function handleClick(event) {  // 'event' has implicit 'any'
    console.log(event);
  }
  ```

### Naming Conventions
- **Components**: `PascalCase` — descriptive nouns (`ChatWindow`, `MessageBubble`, `IconButton`)
- **Functions/Variables**: `camelCase` — descriptive verbs/nouns (`sendMessage`, `isConnected`, `connectionState`)
- **Constants**: `UPPER_SNAKE_CASE` — global constants (`WS_URL`, `MAX_RETRIES`, `INITIAL_BACKOFF_MS`)
- **Types/Interfaces**: `PascalCase` — descriptive nouns ending in "Props", "State", or "Config" for clarity
  - Props: `ChatWindowProps`, `ButtonProps`
  - State: `ConnectionState`, `MessageState`
  - Config: `WebSocketConfig`, `ThemeConfig`
- **Private members**: Prefix with `_` or use `#` for truly private fields
- **Event handlers**: Prefix with `handle` or `on` (`handleSubmit`, `onMessageReceived`)
- **Boolean variables**: Prefix with `is`, `has`, `should` (`isLoading`, `hasError`, `shouldRetry`)

### File Organization
```
src/
├── app/              # Next.js App Router pages
├── components/       # React components
│   ├── chat/        # Feature-specific components
│   ├── data/
│   ├── layout/
│   ├── settings/
│   └── ui/          # Reusable UI components
├── lib/             # Utility functions and clients
├── stores/          # Zustand state stores
└── types/           # Shared TypeScript types
```

- **One component per file**: Export component as default or named export
- **Colocation**: Keep related files together (component + styles + tests)
- **Barrel exports**: Use `index.ts` for public API of feature directories

## React & Next.js Best Practices

### Component Structure
```typescript
"use client";  // Only for client components

import { useState, useEffect } from "react";
import type { ReactNode } from "react";

// 1. Type definitions
interface ChatWindowProps {
  initialMessages: Message[];
  onSendMessage: (text: string) => Promise<void>;
  className?: string;
}

// 2. Component function
export function ChatWindow({
  initialMessages,
  onSendMessage,
  className = "",
}: ChatWindowProps) {
  // 3. Hooks (useState, useEffect, custom hooks)
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [isLoading, setIsLoading] = useState(false);

  // 4. Event handlers
  const handleSend = async (text: string) => {
    setIsLoading(true);
    try {
      await onSendMessage(text);
    } finally {
      setIsLoading(false);
    }
  };

  // 5. Effects
  useEffect(() => {
    // Setup and cleanup
    return () => {
      // Cleanup
    };
  }, []);

  // 6. Render
  return (
    <div className={`chat-window ${className}`}>
      {/* JSX content */}
    </div>
  );
}
```

### State Management
- **Shared app/client state**: Use Zustand for cross-component, persisted, or long-lived client state
- **Fetched/remote data**: Keep it in component state when it is local to a feature, or use a dedicated server-state library when caching, synchronization, or revalidation is needed
- **Local UI state**: Component state is fine (`useState` for toggles, modals)
- **Zustand patterns**:
  ```typescript
  // stores/chatStore.ts
  import { create } from "zustand";

  interface ChatState {
    messages: Message[];
    isConnected: boolean;
    addMessage: (message: Message) => void;
    setConnected: (connected: boolean) => void;
  }

  export const useChatStore = create<ChatState>((set) => ({
    messages: [],
    isConnected: false,
    addMessage: (message) =>
      set((state) => ({ messages: [...state.messages, message] })),
    setConnected: (connected) => set({ isConnected: connected }),
  }));
  ```

### Client vs Server Components
- **Default to Server Components**: Only add `"use client"` when needed
- **Use client components for**:
  - Event handlers (onClick, onChange)
  - Browser APIs (localStorage, WebSocket)
  - React hooks (useState, useEffect, useRef)
  - Context providers
- **Server components for**:
  - Static content
  - Data fetching
  - Direct database/API access

### API Integration
- **Zod validation**: Validate all API responses
  ```typescript
  import { z } from "zod";

  const MessageSchema = z.object({
    id: z.string(),
    text: z.string(),
    sender: z.enum(["user", "assistant"]),
    timestamp: z.number(),
  });

  type Message = z.infer<typeof MessageSchema>;

  async function fetchMessages(): Promise<Message[]> {
    const response = await fetch("/api/messages");
    const data = await response.json();
    return z.array(MessageSchema).parse(data);
  }
  ```
- **Error handling**: Always handle errors gracefully
- **Loading states**: Show loading indicators for async operations

### Accessibility
- **Required attributes**:
  - Images: `alt` text
  - Buttons: `aria-label` for icon-only buttons
  - Forms: `htmlFor` on labels, `id` on inputs
  - Interactive elements: Keyboard navigation support
- **Semantic HTML**: Use `<button>`, `<nav>`, `<main>`, `<section>` appropriately
- **Focus management**: Handle focus states for modals and navigation

### Performance
- **Lazy loading**: Use `React.lazy()` for code splitting
- **Memoization**: Use `useMemo` and `useCallback` for expensive computations
  - But don't overuse — profile first
- **Image optimization**: Use Next.js `<Image>` component
- **Bundle size**: Monitor with `pnpm build` and analyze

## Styling with Tailwind

### Best Practices
- **Utility-first**: Use Tailwind classes directly in JSX
- **Component variants**: Extract to objects for reusability
  ```typescript
  const variantStyles = {
    primary: "bg-blue-500 text-white hover:bg-blue-600",
    secondary: "bg-gray-700 text-gray-100 hover:bg-gray-600",
  };
  ```
- **Avoid inline styles**: Use Tailwind classes instead
- **Responsive design**: Use Tailwind breakpoints (`sm:`, `md:`, `lg:`)
- **Dark mode**: Use `dark:` prefix for dark mode styles

## Testing

### Unit Testing (Vitest)
- **Test files**: Colocate with components (`Component.test.tsx`)
- **Testing Library**: Use `@testing-library/react`
- **Coverage**: Aim for >80% coverage on critical paths
- **Test structure**:
  ```typescript
  import { render, screen } from "@testing-library/react";
  import { expect, test } from "vitest";
  import { IconButton } from "./IconButton";

  test("renders button with children", () => {
    render(<IconButton>Click me</IconButton>);
    expect(screen.getByText("Click me")).toBeInTheDocument();
  });
  ```

### E2E Testing (Playwright)
- **Test critical flows**: User journeys, form submissions
- **Page objects**: Organize selectors and actions

## Common Patterns

### WebSocket Client
```typescript
class WebSocketClient {
  private ws: WebSocket | null = null;
  private messageHandlers: Set<MessageHandler> = new Set();

  connect(): void {
    this.ws = new WebSocket(WS_URL);
    this.ws.onmessage = this.handleMessage;
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    // Return cleanup function
    return () => this.messageHandlers.delete(handler);
  }
}
```

### Custom Hooks
```typescript
function useWebSocket(url: string) {
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");

  useEffect(() => {
    const client = new WebSocketClient(url);
    client.onStatusChange(setConnectionState);
    client.connect();

    return () => client.disconnect();
  }, [url]);

  return connectionState;
}
```

## Error Handling
- **Try-catch blocks**: For async operations
- **Error boundaries**: For React component errors
- **User feedback**: Show error messages to users
- **Logging**: Use `console.error` for development, structured logging for production

## Pre-Commit Checklist
- [ ] TypeScript compiles (`pnpm tsc --noEmit`)
- [ ] ESLint passes (`pnpm lint`)
- [ ] Tests pass (`pnpm test:unit`)
- [ ] No `any` types (except where absolutely necessary)
- [ ] Zod validation on API boundaries
- [ ] Accessibility attributes on interactive elements
- [ ] Server/client components correctly marked

## Git Workflow
See root `CLAUDE.md` for branch naming and commit message conventions.
