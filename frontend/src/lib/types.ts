// Response shapes of the backend API (backend/app/api/*).

export type User = { id: string; email: string; display_name: string | null };
export type Tenant = { id: string; name: string; kind: string };
export type Me = { user: User; tenant: Tenant };

export type Conversation = { id: string; title: string; created_at: string; updated_at: string };
export type HistoryMessage = { id: string | null; role: "user" | "assistant"; content: string };
