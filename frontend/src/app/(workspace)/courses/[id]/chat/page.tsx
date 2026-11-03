import type { Metadata } from "next";
import CourseChat from "@/features/chat/components/course-chat";
import { Suspense } from "react";
import { Spinner } from "@/components/ui";

export const metadata: Metadata = { title: "课程问答" };
export default function Page() {
  return (
    <Suspense fallback={<Spinner label="正在读取课程问答" />}>
      <CourseChat />
    </Suspense>
  );
}
