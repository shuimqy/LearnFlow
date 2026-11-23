import { proxyApi } from "@/lib/proxy-api";

export async function GET(request: Request, { params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;
  return proxyApi(request, `/courses/${encodeURIComponent(courseId)}/export`);
}
