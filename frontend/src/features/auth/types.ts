export type User = { id: string; email: string; name: string };
export type AppMode = "personal" | "multiuser";
export type UserSession = User & { mode: AppMode };
