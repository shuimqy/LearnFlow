import { proxyApi } from "@/lib/proxy-api";

export function POST(request: Request) {
  return proxyApi(request, "/courses/import");
}
