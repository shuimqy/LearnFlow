"use client";

import { FormEvent, useRef, useState } from "react";
import { Check, FileText, LoaderCircle, UploadCloud, X } from "lucide-react";
import { errorMessage } from "@/lib/http";
import { formatBytes } from "@/lib/format";
import { uploadPdf } from "@/features/documents/api";
import { Modal, Notice } from "@/components/ui";

const modes = [
  { value: "original", title: "提取原题", description: "保留课件已有的习题" },
  { value: "generated", title: "生成新题", description: "根据知识点生成习题" },
  { value: "both", title: "两者都要", description: "同时保留原题和新题" },
];

export function UploadForm({
  courseId,
  onClose,
  onUploaded,
}: {
  courseId: string;
  onClose: () => void;
  onUploaded: () => Promise<void>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState("both");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  function choose(files: FileList | null) {
    setError("");
    if (!files?.length) return;
    if (files.length > 1) {
      setError("请一次上传一份课件");
      return;
    }
    const next = files[0];
    if (!next.name.toLowerCase().endsWith(".pdf")) {
      setError("请选择 PDF 格式的课件");
      return;
    }
    if (next.size > 25 * 1024 * 1024) {
      setError("单个文件不能超过 25 MB");
      return;
    }
    setFile(next);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    setProgress(0);
    try {
      await uploadPdf(courseId, file, mode, setProgress);
      await onUploaded();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }
  return (
    <Modal
      title="上传课件"
      description="保留原始 PDF，自动提取知识点、公式和原有题目并存入课程知识库。"
      onClose={onClose}
      busy={busy}
    >
      <form className="form-stack" onSubmit={submit}>
        <input
          type="file"
          ref={input}
          accept="application/pdf,.pdf"
          className="visually-hidden"
          aria-label="选择 PDF 文件"
          disabled={busy}
          onChange={(event) => {
            choose(event.target.files);
            event.target.value = "";
          }}
        />
        {file ? (
          <div className="selected-file">
            <span className="file-icon">
              <FileText size={23} />
            </span>
            <div>
              <strong>{file.name}</strong>
              <span>{formatBytes(file.size)} · PDF 文档</span>
            </div>
            <button
              className="icon-button"
              type="button"
              aria-label="移除所选文件"
              disabled={busy}
              onClick={() => setFile(null)}
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <button
            type="button"
            className={`dropzone ${dragging ? "dragging" : ""}`}
            disabled={busy}
            onClick={() => input.current?.click()}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              choose(event.dataTransfer.files);
            }}
          >
            <UploadCloud size={29} strokeWidth={1.4} />
            <strong>点击选择，或将课件拖到这里</strong>
            <span>PDF 格式，单个文件不超过 25 MB</span>
          </button>
        )}
        <fieldset className="exercise-field" disabled={busy}>
          <legend>后续习题整理方式</legend>
          <p className="field-hint">先保存偏好，习题整理开放后使用。</p>
          <div className="exercise-options">
            {modes.map((item) => (
              <label
                key={item.value}
                className={`exercise-option ${mode === item.value ? "selected" : ""}`}
              >
                <input
                  type="radio"
                  name="exercise-mode"
                  value={item.value}
                  checked={mode === item.value}
                  onChange={() => setMode(item.value)}
                />
                <span className="radio-mark">{mode === item.value && <Check size={11} />}</span>
                <strong>{item.title}</strong>
                <span>{item.description}</span>
              </label>
            ))}
          </div>
        </fieldset>
        {busy && (
          <div className="upload-progress" role="status">
            <div>
              <span>{progress === 100 ? "正在校验并保存文件…" : "正在上传…"}</span>
              <span>{progress}%</span>
            </div>
            <progress value={progress} max={100} aria-label="文件上传进度" />
          </div>
        )}
        {error && <Notice message={error} />}
        <div className="modal-actions">
          <button type="button" className="button secondary" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button className="button primary" disabled={!file || busy}>
            {busy ? <LoaderCircle size={16} className="spin" /> : <UploadCloud size={16} />}上传课件
          </button>
        </div>
      </form>
    </Modal>
  );
}
