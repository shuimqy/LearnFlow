"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, LoaderCircle, RefreshCw } from "lucide-react";
import { Notice, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/http";
import type { Document } from "../types";
import type { Extraction } from "../extraction-types";

export default function ExtractionWorkspace() {
  const { id: courseId, documentId } = useParams<{ id: string; documentId: string }>();
  const router = useRouter();
  const base = `/documents/${documentId}/extraction`;
  const [document, setDocument] = useState<Document | null>(null);
  const [overview, setOverview] = useState<Extraction | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const [docs, result] = await Promise.all([
          api<Document[]>(`/courses/${courseId}/documents`, { signal }),
          api<Extraction>(base, { signal }),
        ]);
        if (signal?.aborted) return;
        const found = docs.find((doc) => doc.id === documentId);
        if (!found) throw new Error("课件不属于当前课程，或已被删除");
        setDocument(found);
        setOverview(result);
        setError("");
      } catch (err) {
        if (!signal?.aborted) setError(errorMessage(err));
      }
    },
    [base, courseId, documentId],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  const running = overview?.task.status === "queued" || overview?.task.status === "running";
  useEffect(() => {
    if (!running) return;
    const controller = new AbortController();
    const timer = setInterval(() => void load(controller.signal), 3000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [load, running]);
  useEffect(() => {
    if (overview?.task.status === "completed" && overview.task.stage === "imported") {
      router.replace(`/courses/${courseId}/knowledge`);
    }
  }, [overview?.task.status, overview?.task.stage, courseId, router]);
  async function start() {
    setBusy(true);
    try {
      await api(base, { method: "POST" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  if (!document || !overview)
    return error ? (
      <Notice message={error} retry={() => void load()} />
    ) : (
      <Spinner label="正在读取处理记录" />
    );
  const completed = overview.pages.filter((page) => page.status === "completed").length;
  const imported = overview.pages.reduce(
    (sum, page) => sum + (page.counts.imported || 0) + (page.counts.accepted || 0),
    0,
  );
  const failed = overview.pages.filter((page) => page.status === "failed");
  return (
    <>
      <Link href={`/courses/${courseId}`} className="back-link">
        <ArrowLeft size={15} />
        返回课程课件
      </Link>
      <div className="extraction-heading">
        <div>
          <h1>课件处理进度</h1>
          <p>
            {document.filename} · 已识别 {completed} / {overview.page_count} 页 · 已入库 {imported}{" "}
            条
          </p>
        </div>
        <Link className="button secondary" href={`/courses/${courseId}/knowledge`}>
          课程知识库
          <ArrowUpRight size={14} />
        </Link>
      </div>
      {error && <Notice message={error} />}
      <section className="extraction-status" aria-live="polite">
        <div>
          {running ? (
            <>
              <LoaderCircle size={16} className="spin" />
              <span>
                {overview.task.status === "queued"
                  ? "已加入队列，等待后台处理"
                  : `正在识别并存入知识库 · ${overview.task.progress}%`}
              </span>
            </>
          ) : (
            <span>
              {overview.task.error ||
                (overview.task.status === "completed"
                  ? "识别已完成，正在打开课程知识库。"
                  : "开始后自动提取知识点、公式和原有题目，并存入课程知识库。")}
            </span>
          )}
        </div>
        {!running && overview.task.status !== "completed" && (
          <button className="button secondary" disabled={busy} onClick={() => void start()}>
            <RefreshCw size={14} />
            {busy ? "正在提交…" : overview.task.status === "failed" ? "重试未完成页面" : "开始识别"}
          </button>
        )}
      </section>
      {running && (
        <progress
          className="extraction-progress"
          value={overview.task.progress}
          max={100}
          aria-label="课件识别进度"
        />
      )}
      {failed.length > 0 && (
        <div className="extraction-failures">
          {failed.map((page) => (
            <p key={page.id}>
              第 {page.page_number} 页：{page.error || "识别失败"}
            </p>
          ))}
        </div>
      )}
    </>
  );
}
