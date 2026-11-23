export async function proxyApi(request: Request, path: string) {
  const origin = process.env.API_ORIGIN || "http://127.0.0.1:8000";
  const url = new URL(`/api${path}`, origin);
  url.search = new URL(request.url).search;

  const headers = new Headers();
  for (const name of ["cookie", "origin", "sec-fetch-site", "content-type", "content-length"]) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (host) headers.set("x-forwarded-host", host);

  // 转发原始 multipart 流，避免 Next.js 重写代理复制上传正文。
  const options: RequestInit & { duplex: "half" } = {
    method: request.method,
    headers,
    body: request.body,
    duplex: "half",
    cache: "no-store",
    redirect: "manual",
    signal: request.signal,
  };
  try {
    const upstream = await fetch(url, options);
    const responseHeaders = new Headers();
    for (const name of [
      "content-type",
      "content-disposition",
      "cache-control",
      "x-request-id",
      "x-content-type-options",
    ]) {
      const value = upstream.headers.get(name);
      if (value !== null) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json({ detail: "服务暂时不可用，请稍后重试" }, { status: 502 });
  }
}
