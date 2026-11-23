import { uploadForm } from "@/lib/http";
import type { Document } from "./types";

export function uploadPdf(
  courseId: string,
  file: File,
  onProgress: (value: number) => void,
): Promise<Document> {
  const form = new FormData();
  form.append("file", file);
  form.append("exercise_mode", "original");
  return uploadForm(`/courses/${courseId}/documents`, form, onProgress);
}
