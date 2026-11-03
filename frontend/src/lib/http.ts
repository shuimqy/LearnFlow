export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new ApiError(0, "连接中断，请检查网络后重试");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (response.status === 401 && !path.startsWith("/auth/")) {
      window.location.assign("/login");
    }
    throw new ApiError(
      response.status,
      typeof body?.detail === "string" ? body.detail : "暂时无法连接服务，请稍后重试",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败，请重试";
}
