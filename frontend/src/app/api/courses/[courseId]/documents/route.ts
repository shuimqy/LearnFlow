import { proxyApi } from "@/lib/proxy-api";

type Context = { params: Promise<{ courseId: string }> };

async function forwardDocuments(request: Request, { params }: Context) {
  const { courseId } = await params;
  return proxyApi(request, `/courses/${encodeURIComponent(courseId)}/documents`);
}

export const GET = forwardDocuments;
export const POST = forwardDocuments;
