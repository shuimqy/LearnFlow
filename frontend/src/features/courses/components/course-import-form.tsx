"use client";

import { useRef, useState, type FormEvent } from "react";
import { FileArchive, LoaderCircle, Upload, X } from "lucide-react";
import { Modal, Notice } from "@/components/ui";
import type { Course } from "@/features/courses/types";
import { formatBytes } from "@/lib/format";
import { errorMessage, uploadForm } from "@/lib/http";

export function CourseImportForm({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (course: Course) => Promise<void>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [selection, setSelection] = useState<{ file: File; requestId?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  function choose(file?: File) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setError("请选择 LearnFlow 导出的 ZIP 课程包");
      return;
    }
    setError("");
    setSelection({ file, requestId: crypto.randomUUID?.() });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selection || busy) return;
    setError("");
    setBusy(true);
    setProgress(0);
    const form = new FormData();
    form.append("file", selection.file);
    if (selection.requestId) form.append("request_id", selection.requestId);
    try {
      const course = await uploadForm<Course>("/courses/import", form, setProgress);
      await onImported(course);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Modal
      title="导入课程"
      description="选择 LearnFlow 导出的 ZIP 课程包，导入后会创建一门新课程。"
      onClose={onClose}
      busy={busy}
    >
      <form className="form-stack" onSubmit={submit}>
        <input
          type="file"
          ref={input}
          accept=".zip,application/zip"
          hidden
          aria-label="选择 ZIP 课程包"
          disabled={busy}
          onChange={(event) => {
            choose(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        {selection ? (
          <div className="selected-file">
            <span className="file-icon">
              <FileArchive size={23} />
            </span>
            <div>
              <strong>{selection.file.name}</strong>
              <span>{formatBytes(selection.file.size)}</span>
            </div>
            <button
              className="icon-button"
              type="button"
              aria-label="移除所选文件"
              disabled={busy}
              onClick={() => {
                setSelection(null);
                setError("");
              }}
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <button type="button" className="dropzone" onClick={() => input.current?.click()}>
            <FileArchive size={29} strokeWidth={1.4} />
            <strong>选择 ZIP 课程包</strong>
          </button>
        )}
        {busy && (
          <div className="upload-progress" role="status">
            <div>
              <span>{progress === 100 ? "正在校验并导入课程…" : "正在上传课程包…"}</span>
              {progress < 100 && <span>{progress}%</span>}
            </div>
            <progress
              value={progress === 100 ? undefined : progress}
              max={100}
              aria-label={progress === 100 ? "正在导入课程" : "课程包上传进度"}
            />
          </div>
        )}
        {error && <Notice message={error} />}
        <div className="modal-actions">
          <button type="button" className="button secondary" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button className="button primary" disabled={!selection || busy}>
            {busy ? <LoaderCircle size={16} className="spin" /> : <Upload size={16} />}
            导入课程
          </button>
        </div>
      </form>
    </Modal>
  );
}
