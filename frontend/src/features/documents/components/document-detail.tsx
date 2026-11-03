"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Notice, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/http";
import { ChapterOrganizer } from "@/features/chapters/components/chapter-organizer";
import type { Document } from "../types";
import "../document-detail.css";

export default function DocumentDetail() {
  const { id, documentId } = useParams<{ id: string; documentId: string }>();
  const [document, setDocument] = useState<Document | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void api<Document[]>(`/courses/${id}/documents`, { signal: controller.signal })
      .then((docs) => {
        if (controller.signal.aborted) return;
        const found = docs.find((doc) => doc.id === documentId);
        if (found) setDocument(found);
        else setError("课件不存在或不属于当前课程。");
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      });
    return () => controller.abort();
  }, [id, documentId]);
  if (error) return <Notice message={error} />;
  if (!document) return <Spinner label="正在读取课件" />;
  return (
    <>
      <Link className="back-link" href={`/courses/${id}`}>
        <ArrowLeft size={15} />
        返回课程资料
      </Link>
      <div className="page-heading">
        <div>
          <h1>课件详情</h1>
          <p>
            {document.filename} · {document.page_count} 页
          </p>
        </div>
      </div>
      <div className="document-detail-actions">
        <a
          className="button secondary"
          href={`/api/documents/${document.id}/file`}
          target="_blank"
          rel="noreferrer"
        >
          查看原始 PDF
        </a>
        <Link
          className="button secondary"
          href={`/courses/${id}/documents/${document.id}/extraction`}
        >
          识别进度
        </Link>
        <Link className="button secondary" href={`/courses/${id}/workbooks`}>
          整理做题本
        </Link>
      </div>
      <ChapterOrganizer courseId={id} documents={[document]} initiallyOpen />
    </>
  );
}
