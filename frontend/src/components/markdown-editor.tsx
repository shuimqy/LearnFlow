"use client";

import { useId, useState } from "react";
import { Markdown } from "@/components/markdown";

export function MarkdownEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const [preview, setPreview] = useState(true);
  return (
    <div className="markdown-editor">
      <div className="markdown-editor-heading">
        <label htmlFor={id}>正文（Markdown）</label>
        <button
          type="button"
          className="text-button"
          aria-expanded={preview}
          aria-controls={`${id}-preview`}
          onClick={() => setPreview((visible) => !visible)}
        >
          {preview ? "隐藏预览" : "显示预览"}
        </button>
      </div>
      <div className={`markdown-editor-body ${preview ? "with-preview" : ""}`}>
        <textarea
          id={id}
          className="knowledge-content-input"
          aria-describedby={`${id}-hint`}
          required
          rows={10}
          maxLength={100000}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="写下定义、推导、例子或需要记住的结论"
          disabled={disabled}
        />
        <section
          id={`${id}-preview`}
          className="markdown-editor-preview"
          aria-label="正文预览"
          hidden={!preview}
        >
          <span className="markdown-editor-preview-label">预览</span>
          {value.trim() ? (
            <Markdown>{value}</Markdown>
          ) : (
            <p className="markdown-editor-placeholder">输入正文后，这里会显示排版和公式。</p>
          )}
        </section>
      </div>
      <p id={`${id}-hint`} className="field-hint">
        支持标题、列表、表格和代码。行内公式用 <code>$...$</code>，独立公式用 <code>$$...$$</code>。
      </p>
    </div>
  );
}
