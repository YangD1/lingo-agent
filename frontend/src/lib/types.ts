// Response shapes of the backend API (backend/app/api/*).

export type User = { id: string; email: string; display_name: string | null };
export type Tenant = { id: string; name: string; kind: string };
export type Me = { user: User; tenant: Tenant };
