"use client";

import { FormEvent, useState } from "react";
import { FileText, LoaderCircle, Plus, X } from "lucide-react";
import { Modal, Notice } from "@/components/ui";
import { MarkdownEditor } from "@/components/markdown-editor";
import { api, errorMessage } from "@/lib/http";
import type { Document } from "@/features/documents/types";
import type { ExtractedPage, KnowledgePoint, SourceInput } from "../types";

type SourceRow = SourceInput & { key: string; preview?: ExtractedPage };

export function KnowledgeForm({
  courseId,
  point,
  documents,
  mode,
  onClose,
  onSaved,
}: {
  courseId: string;
  point?: KnowledgePoint;
  documents: Document[];
  mode: "create" | "edit" | "proposal";
  onClose: () => void;
  onSaved: (pointId: string, proposal: boolean) => Promise<void>;
}) {
  const [title, setTitle] = useState(point?.title || "");
  const [summary, setSummary] = useState(point?.summary || "");
  const [content, setContent] = useState(point?.content || "");
  const [reason, setReason] = useState("");
  const [sources, setSources] = useState<SourceRow[]>(() =>
    (point?.sources || []).map((source) => ({
      key: source.id,
      source_id: source.id,
      document_id: source.document_id,
      page_number: source.page_number,
      quote: source.quote,
    })),
  );
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState<string | null>(null);
  const [error, setError] = useState("");
  function changeSource(key: string, change: Partial<SourceRow>) {
    setSources((rows) => rows.map((row) => (row.key === key ? { ...row, ...change } : row)));
  }
  async function readPage(row: SourceRow) {
    if (!row.document_id) return;
    setReading(row.key);
    setError("");
    try {
      const result = await api<ExtractedPage>(
        `/documents/${row.document_id}/pages/${row.page_number}/extract`,
        { method: "POST" },
      );
      changeSource(row.key, { preview: result });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setReading(null);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const base = `/courses/${courseId}/knowledge`;
    try {
      const result = await api<{ id: string; knowledge_id?: string }>(
        mode === "create" ? base : `${base}/${point!.id}${mode === "proposal" ? "/proposals" : ""}`,
        {
          method: mode === "edit" ? "PATCH" : "POST",
          body: JSON.stringify({
            title,
            summary,
            content,
            sources: sources.map(({ document_id, source_id, page_number, quote }) => ({
              document_id,
              source_id,
              page_number,
              quote,
            })),
            ...(point ? { expected_version: point.version, reason } : {}),
          }),
        },
      );
      await onSaved(mode === "proposal" ? point!.id : result.id, mode === "proposal");
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }
  const heading =
    mode === "create" ? "添加知识点" : mode === "edit" ? "编辑知识点" : "提出修改建议";
  return (
    <Modal
      title={heading}
      description={
        mode === "proposal"
          ? "说明要修正的问题，正文可保留当前版本。保存建议后，可交由模型审查并处理。"
          : "正文与课件原文分别保存，修改会保留历史记录。"
      }
      onClose={onClose}
      busy={busy || !!reading}
      wide
    >
      <form className="form-stack" onSubmit={submit}>
        <label>
          知识点标题
          <input
            autoFocus
            required
            maxLength={200}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="例如：线性无关的判断"
            disabled={busy}
          />
        </label>
        <label>
          简要说明 <span className="optional">选填</span>
          <textarea
            rows={2}
            maxLength={2000}
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            placeholder="用一两句话说明这个知识点"
            disabled={busy}
          />
        </label>
        <MarkdownEditor value={content} onChange={setContent} disabled={busy} />
        <fieldset className="knowledge-sources-field" disabled={busy}>
          <legend>
            课件引用 <span className="optional">选填</span>
          </legend>
          <div className="field-heading">
            <span className="field-hint">原文与知识正文分别保存。</span>
            <button
              type="button"
              className="text-button"
              disabled={!documents.length || sources.length >= 20 || !!reading}
              onClick={() =>
                setSources((rows) => [
                  ...rows,
                  {
                    key: crypto.randomUUID(),
                    document_id: documents[0].id,
                    page_number: 1,
                    quote: "",
                  },
                ])
              }
            >
              <Plus size={13} />
              添加引用
            </button>
          </div>
          {!sources.length && (
            <p className="field-hint">
              {documents.length
                ? "关联课件与页码，方便之后核对。也可以先保存独立笔记。"
                : "上传课件后，可以关联原始页码。目前可先保存独立笔记。"}
            </p>
          )}
          {sources.map((row) => {
            const document = documents.find((item) => item.id === row.document_id);
            return (
              <div key={row.key} className="source-editor">
                <div className="source-editor-controls">
                  <label>
                    课件
                    <select
                      aria-label="引用课件"
                      value={row.document_id || ""}
                      required={!row.source_id}
                      onChange={(event) =>
                        changeSource(row.key, {
                          document_id: event.target.value,
                          source_id: undefined,
                          page_number: 1,
                          quote: "",
                          preview: undefined,
                        })
                      }
                    >
                      {!document && (
                        <option value={row.document_id || ""}>原文件已删除，保留原引用</option>
                      )}
                      {documents.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.filename}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="source-page-input">
                    页码
                    <input
                      type="number"
                      min={1}
                      max={document?.page_count}
                      required
                      value={row.page_number}
                      onChange={(event) =>
                        changeSource(row.key, {
                          page_number: Number(event.target.value),
                          quote: "",
                          preview: undefined,
                        })
                      }
                    />
                  </label>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={!row.document_id || !!reading}
                    onClick={() => void readPage(row)}
                  >
                    {reading === row.key ? (
                      <LoaderCircle size={14} className="spin" />
                    ) : (
                      <FileText size={14} />
                    )}
                    读取原文
                  </button>
                  <button
                    className="icon-button"
                    type="button"
                    aria-label="移除引用"
                    disabled={!!reading}
                    onClick={() =>
                      setSources((rows) => rows.filter((item) => item.key !== row.key))
                    }
                  >
                    <X size={15} />
                  </button>
                </div>
                {row.preview && (
                  <div className="source-page-preview">
                    <span>第 {row.page_number} 页原文</span>
                    <pre>
                      {row.preview.text ||
                        (row.preview.status === "needs_ocr"
                          ? "这一页包含图片，暂时没有提取到文字。可以保留页码引用。"
                          : "这一页没有可提取的文字。")}
                    </pre>
                  </div>
                )}
                <label>
                  引用文字 <span className="optional">留空时引用整页</span>
                  <textarea
                    rows={3}
                    maxLength={50000}
                    value={row.quote}
                    onChange={(event) => changeSource(row.key, { quote: event.target.value })}
                    placeholder="从该页原文复制需要引用的片段"
                    disabled={!row.document_id}
                  />
                </label>
              </div>
            );
          })}
        </fieldset>
        {point && (
          <label>
            {mode === "proposal" ? "建议原因" : "修改原因"}
            <textarea
              required
              rows={2}
              maxLength={2000}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="说明哪里有误，或为什么需要补充"
              disabled={busy}
            />
          </label>
        )}
        {error && <Notice message={error} />}
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            disabled={busy || !!reading}
            onClick={onClose}
          >
            取消
          </button>
          <button
            className="button primary"
            disabled={
              busy || !!reading || !title.trim() || !content.trim() || (!!point && !reason.trim())
            }
          >
            {busy && <LoaderCircle size={15} className="spin" />}
            {mode === "proposal" ? "提交建议" : mode === "edit" ? "保存修订" : "保存知识点"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
