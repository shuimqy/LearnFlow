"use client";

import Link from "next/link";
import type { Document } from "@/features/documents/types";
import type { Chapter } from "@/features/chapters/types";

export type WorkbookScope = {
  document_ids: string[];
  chapter_ids: string[];
  page_from: string;
  page_to: string;
};

export function WorkbookSources({
  courseId,
  documents,
  chapters,
  scope,
  onChange,
  disabled,
}: {
  courseId: string;
  documents: Document[];
  chapters: Chapter[];
  scope: WorkbookScope;
  onChange: (scope: WorkbookScope) => void;
  disabled: boolean;
}) {
  const available = chapters.filter((chapter) => scope.document_ids.includes(chapter.document_id));
  return (
    <section className="workbook-sources" aria-label="来源课件与选题范围">
      <div className="workbook-source-heading">
        <h2>1. 选择来源课件</h2>
        <span>
          已选 {scope.document_ids.length} / {documents.length} 份
        </span>
      </div>
      <p className="workbook-note">
        可将多份课件的题目合成一本。下面的范围同时用于手动选题和自动整理，已加入本册的题目会保留。
      </p>
      <fieldset disabled={disabled}>
        <div className="workbook-source-actions">
          <button
            type="button"
            className="text-button"
            onClick={() => onChange({ ...scope, document_ids: documents.map((doc) => doc.id) })}
          >
            全选课件
          </button>
          <button
            type="button"
            className="text-button"
            onClick={() => onChange({ ...scope, document_ids: [], chapter_ids: [] })}
          >
            清空选择
          </button>
          <a className="text-button" href="#workbook-picker">
            手动挑选题目 ↓
          </a>
        </div>
        <div className="workbook-source-list">
          {documents.map((doc) => (
            <div className="workbook-source-row" key={doc.id}>
              <label className="workbook-check">
                <input
                  type="checkbox"
                  checked={scope.document_ids.includes(doc.id)}
                  onChange={(event) => {
                    const ids = event.target.checked
                      ? [...scope.document_ids, doc.id]
                      : scope.document_ids.filter((id) => id !== doc.id);
                    onChange({
                      ...scope,
                      document_ids: ids,
                      chapter_ids: scope.chapter_ids.filter((id) =>
                        chapters.some(
                          (chapter) => chapter.id === id && ids.includes(chapter.document_id),
                        ),
                      ),
                    });
                  }}
                />
                <span>
                  {doc.filename}
                  <small>{doc.page_count} 页</small>
                </span>
              </label>
              <Link
                href={`/courses/${courseId}/documents/${doc.id}`}
                target="_blank"
                rel="noreferrer"
                title="在新标签页管理章节"
              >
                管理章节 ↗
              </Link>
            </div>
          ))}
        </div>
        {!documents.length && <p className="workbook-note">请先在课程资料页上传并识别课件。</p>}
        {documents.length > 0 && !scope.document_ids.length && (
          <p className="workbook-warnings">请至少选择一份课件，才能查找或自动整理题目。</p>
        )}
        <details className="workbook-source-ranges">
          <summary>限定章节或页码（可选）</summary>
          <p className="workbook-note">
            不填写则使用所选课件的全部题目。页码为 PDF
            物理页码，同时适用于每份所选课件；章节和页码同时填写时取交集。
          </p>
          <div className="assembly-chapters">
            {available.map((chapter) => (
              <label className="workbook-check" key={chapter.id}>
                <input
                  type="checkbox"
                  checked={scope.chapter_ids.includes(chapter.id)}
                  onChange={(event) =>
                    onChange({
                      ...scope,
                      chapter_ids: event.target.checked
                        ? [...scope.chapter_ids, chapter.id]
                        : scope.chapter_ids.filter((id) => id !== chapter.id),
                    })
                  }
                />
                <span>
                  {chapter.title} · {chapter.filename}
                  <small>
                    第 {chapter.start_page}–{chapter.end_page} 页 · {chapter.exercise_count} 题
                  </small>
                </span>
              </label>
            ))}
          </div>
          {!available.length && (
            <p className="workbook-note">
              所选课件尚未划分章节。可直接按页码选题，需要分章时点击课件旁的“管理章节”。
            </p>
          )}
          <div className="workbook-source-pages">
            <label>
              起始页
              <input
                aria-label="起始页"
                type="number"
                min={1}
                value={scope.page_from}
                placeholder="不限"
                onChange={(event) => onChange({ ...scope, page_from: event.target.value })}
              />
            </label>
            <label>
              结束页
              <input
                aria-label="结束页"
                type="number"
                min={scope.page_from || 1}
                value={scope.page_to}
                placeholder="不限"
                onChange={(event) => onChange({ ...scope, page_to: event.target.value })}
              />
            </label>
          </div>
          {scope.chapter_ids.length > 0 && (
            <button
              type="button"
              className="text-button"
              onClick={() => onChange({ ...scope, chapter_ids: [] })}
            >
              清除章节限制
            </button>
          )}
        </details>
      </fieldset>
    </section>
  );
}
