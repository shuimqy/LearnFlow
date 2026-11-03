import type { Document } from "./types";

export function uploadPdf(
  courseId: string,
  file: File,
  mode: string,
  onProgress: (value: number) => void,
): Promise<Document> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/courses/${courseId}/documents`);
    xhr.timeout = 120_000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () => reject(new Error("上传中断，请检查网络后重试"));
    xhr.ontimeout = () => reject(new Error("上传超时，请稍后重试"));
    xhr.onload = () => {
      let body;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        reject(new Error("服务暂时不可用，请稍后重试"));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else {
        if (xhr.status === 401) window.location.assign("/login");
        reject(new Error(body.detail || "上传失败，请重试"));
      }
    };
    const form = new FormData();
    form.append("file", file);
    form.append("exercise_mode", mode);
    xhr.send(form);
  });
}
