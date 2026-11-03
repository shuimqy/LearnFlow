"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api, errorMessage } from "@/lib/http";
import { Notice, Spinner } from "@/components/ui";
import type { Document } from "@/features/documents/types";
import type { Chapter, StructureState } from "../types";
import "../chapter-organizer.css";

export function ChapterOrganizer({
  courseId,
  documents,
  onChanged,
  initiallyOpen = false,
}: {
  courseId: string;
  documents: Document[];
  onChanged?: () => void;
  initiallyOpen?: boolean;
}) {
  const [documentId, setDocumentId] = useState(documents[0]?.id || "");
  const [state, setState] = useState<StructureState | null>(null);
  const [chapters, setChapters] = useState<Partial<Chapter>[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [refresh, setRefresh] = useState(0);
  const running = state?.status === "queued" || state?.status === "running";
  useEffect(() => {
    if (!documentId) return;
    const controller = new AbortController();
    void api<StructureState>(`/documents/${documentId}/structure`, { signal: controller.signal })
      .then((next) => {
        if (controller.signal.aborted) return;
        setState(next);
        if (!dirty) setChapters(next.chapters);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      });
    return () => controller.abort();
  }, [documentId, refresh, dirty]);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setRefresh((value) => value + 1), 2500);
    return () => clearInterval(timer);
  }, [running]);
  useEffect(() => {
    if (state?.status === "completed") onChanged?.();
  }, [state?.status, state?.version, onChanged]);
  async function action(recognize: boolean) {
    if (!documentId || !state) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (recognize) {
        const next = await api<StructureState>(`/documents/${documentId}/structure`, {
          method: "POST",
          body: JSON.stringify({ expected_version: state.version }),
        });
        setState({ ...next, chapters: state.chapters });
        setMessage(next.status === "failed" ? "" : "已提交章节与题目整理任务。");
      } else {
        const next = await api<StructureState>(`/documents/${documentId}/chapters`, {
          method: "PUT",
          body: JSON.stringify({ expected_version: state.version, chapters }),
        });
        setState(next);
        setChapters(next.chapters);
        setDirty(false);
        setMessage(
          next.chapters.length
            ? "章节已保存，题目和知识点按来源页码关联。"
            : "已清空章节，仍可按课件或页码选题。",
        );
        onChanged?.();
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  function edit(index: number, values: Partial<Chapter>) {
    setChapters((rows) => rows.map((row, i) => (i === index ? { ...row, ...values } : row)));
    setDirty(true);
  }
  if (!documents.length)
    return <p className="chapter-note">上传课件并识别后，可在这里整理章节。</p>;
  return (
    <details className="chapter-organizer" open={initiallyOpen}>
      <summary>章节与原题整理</summary>
      <p className="chapter-note">
        章节用于按课件页码筛选题目和知识点。例如，把第 1–20
        页命名为“第二章”，选题时选择它，就只整理这些页的题目。只整理整份课件时，可以跳过章节划分。
      </p>
      <p className="chapter-note">
        “自动识别”从课件整理章节和题目标签；“添加章节”让你手动填写名称和页码，不会新增题目。自动识别会使用账号模型，重新识别会替换当前章节，已确认裁片保留。
      </p>
      <div className="chapter-actions">
        {documents.length > 1 && (
          <label>
            整理课件
            <select
              value={documentId}
              disabled={busy || dirty || running}
              onChange={(event) => {
                setDocumentId(event.target.value);
                setState(null);
                setMessage("");
                setError("");
              }}
            >
              {documents.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.filename}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          className="button secondary"
          disabled={busy || running || dirty || !state}
          onClick={() => void action(true)}
        >
          {running ? `整理中 ${state?.progress || 0}%` : "自动识别章节与题目"}
        </button>
      </div>
      {error && <Notice message={error} />}
      {state?.error && <Notice message={state.error} />}
      {message && (
        <p role="status" className="chapter-note">
          {message}
        </p>
      )}
      {state?.warnings.map((warning, i) => (
        <p className="chapter-warnings" key={i}>
          {warning}
        </p>
      ))}
      {!state ? (
        <Spinner label="读取章节" />
      ) : (
        <fieldset disabled={busy || running} className="chapter-edit-list">
          {chapters.map((chapter, index) => (
            <div className="chapter-edit-row" key={chapter.id || `new-${index}`}>
              <label>
                章节名称
                <input
                  aria-label={`章节 ${index + 1} 名称`}
                  value={chapter.title || ""}
                  maxLength={200}
                  onChange={(event) => edit(index, { title: event.target.value })}
                />
              </label>
              <label>
                起始页
                <input
                  aria-label={`章节 ${index + 1} 起始页`}
                  type="number"
                  min={1}
                  max={documents.find((item) => item.id === documentId)?.page_count}
                  value={chapter.start_page || 1}
                  onChange={(event) => edit(index, { start_page: Number(event.target.value) })}
                />
              </label>
              <label>
                结束页
                <input
                  aria-label={`章节 ${index + 1} 结束页`}
                  type="number"
                  min={1}
                  max={documents.find((item) => item.id === documentId)?.page_count}
                  value={chapter.end_page || 1}
                  onChange={(event) => edit(index, { end_page: Number(event.target.value) })}
                />
              </label>
              <button
                className="icon-button"
                aria-label={`删除章节 ${index + 1}`}
                onClick={() => {
                  setChapters((rows) => rows.filter((_, i) => i !== index));
                  setDirty(true);
                }}
              >
                <Trash2 size={15} />
              </button>
              {chapter.id && (
                <div className="chapter-counts">
                  {chapter.exercise_count || 0} 道题 ·{" "}
                  <Link href={`/courses/${courseId}/knowledge?chapter=${chapter.id}`}>
                    {chapter.knowledge_count || 0} 个知识点
                  </Link>
                </div>
              )}
            </div>
          ))}
          {!chapters.length && (
            <p className="chapter-empty">
              这份课件尚未划分章节。可自动识别，也可点击“添加章节”手动填写页码；不分章也能整理全部原题。
            </p>
          )}
          <div className="chapter-actions">
            <button
              className="button secondary"
              disabled={chapters.length >= 100}
              onClick={() => {
                const start = (chapters.at(-1)?.end_page || 0) + 1;
                setChapters((rows) => [
                  ...rows,
                  { title: `第 ${rows.length + 1} 章`, start_page: start, end_page: start },
                ]);
                setDirty(true);
              }}
            >
              <Plus size={15} />
              添加章节
            </button>
            <button className="button primary" disabled={!dirty} onClick={() => void action(false)}>
              保存章节
            </button>
            {dirty && (
              <button
                className="text-button"
                onClick={() => {
                  setChapters(state.chapters);
                  setDirty(false);
                }}
              >
                撤销本次编辑
              </button>
            )}
          </div>
        </fieldset>
      )}
    </details>
  );
}
