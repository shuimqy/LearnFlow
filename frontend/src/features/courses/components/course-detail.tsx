"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Check,
  FileText,
  Info,
  MessageSquare,
  Settings2,
  Trash2,
  Upload,
} from "lucide-react";
import { CourseForm } from "@/features/courses/components/course-form";
import { useCourses } from "@/features/courses/course-provider";
import { Modal, Notice, Spinner } from "@/components/ui";
import { UploadForm } from "@/features/documents/components/upload-form";
import { api, errorMessage } from "@/lib/http";
import type { Course } from "@/features/courses/types";
import type { Document } from "@/features/documents/types";
import { formatBytes, formatDate } from "@/lib/format";

const modeNames: Record<string, string> = {
  both: "原题与新题",
  original: "提取原题",
  generated: "生成新题",
};

export default function CoursePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { refresh } = useCourses();
  const [course, setCourse] = useState<Course | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<Document | "course" | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [success, setSuccess] = useState("");
  const load = useCallback(async () => {
    setError("");
    try {
      const [nextCourse, nextDocuments] = await Promise.all([
        api<Course>(`/courses/${id}`),
        api<Document[]>(`/courses/${id}/documents`),
      ]);
      setCourse(nextCourse);
      setDocuments(nextDocuments);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);
  const processing = documents.some((document) =>
    ["queued", "running"].includes(document.task.status),
  );
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [processing, load]);
  useEffect(() => {
    if (!success) return;
    const timeout = setTimeout(() => setSuccess(""), 5000);
    return () => clearTimeout(timeout);
  }, [success]);
  async function confirmDelete() {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await api(deleting === "course" ? `/courses/${id}` : `/documents/${deleting.id}`, {
        method: "DELETE",
      });
      await refresh();
      if (deleting === "course") router.push("/");
      else {
        await load();
        setSuccess("课件已删除");
      }
      setDeleting(null);
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  }
  if (loading) return <Spinner label="正在读取课程" />;
  if (error)
    return (
      <>
        <Link href="/" className="back-link">
          <ArrowLeft size={15} />
          返回我的课程
        </Link>
        <Notice message={error} retry={() => void load()} />
      </>
    );
  if (!course) return null;
  return (
    <>
      <Link href="/" className="back-link">
        <ArrowLeft size={15} />
        我的课程
      </Link>
      <div className="course-detail-heading">
        <span className={`course-detail-icon tint-${course.color}`}>
          <BookOpen size={30} strokeWidth={1.3} />
        </span>
        <div>
          <span className="eyebrow">课程资料库</span>
          <h1>{course.name}</h1>
          {course.description && <p>{course.description}</p>}
        </div>
        <button className="button secondary" onClick={() => setEditing(true)}>
          <Settings2 size={16} />
          课程设置
        </button>
      </div>
      <div className="course-summary">
        <span>{documents.length} 份课件</span>
        <span>{documents.reduce((sum, document) => sum + document.page_count, 0)} 页资料</span>
        <span>创建于 {formatDate(course.created_at)}</span>
      </div>
      <nav className="course-actions" aria-label="课程功能">
        <Link href={`/courses/${id}/chat`} className="button primary">
          <MessageSquare size={18} />
          课程问答
        </Link>
        <Link href={`/courses/${id}/knowledge`} className="button secondary">
          <BookOpen size={18} />
          课程知识库
        </Link>
        <Link href={`/courses/${id}/workbooks`} className="button secondary">
          <FileText size={18} />
          课件做题本
        </Link>
      </nav>
      <div className="document-toolbar">
        <h2>
          课程课件<span>{documents.length}</span>
        </h2>
        <button className="button primary" onClick={() => setUploading(true)}>
          <Upload size={16} />
          上传课件
        </button>
      </div>
      {success && (
        <div className="success-notice" role="status">
          <Check size={16} />
          {success}
        </div>
      )}
      {documents.length ? (
        <>
          <div className="document-table">
            <div className="document-table-head">
              <span>文件名称</span>
              <span>整理偏好</span>
              <span>状态</span>
              <span>上传日期</span>
              <span />
            </div>
            {documents.map((document) => (
              <div key={document.id} className="document-row">
                <div className="document-name">
                  <span className="file-icon">
                    <FileText size={21} strokeWidth={1.5} />
                  </span>
                  <div>
                    <a href={`/api/documents/${document.id}/file`} target="_blank" rel="noreferrer">
                      {document.filename}
                      <ArrowUpRight size={13} />
                    </a>
                    <span>
                      {document.page_count} 页 · {formatBytes(document.size_bytes)}
                    </span>
                    <Link href={`/courses/${id}/documents/${document.id}`}>课件详情与章节</Link>
                  </div>
                </div>
                <span className="document-mode">{modeNames[document.exercise_mode]}</span>
                <Link
                  href={
                    document.task.status === "completed"
                      ? `/courses/${id}/knowledge`
                      : `/courses/${id}/documents/${document.id}/extraction`
                  }
                  className="document-extraction-link"
                >
                  {document.task.status === "running"
                    ? `识别中 ${document.task.progress}%`
                    : document.task.status === "queued"
                      ? "等待识别"
                      : document.task.status === "completed"
                        ? "查看知识库"
                        : document.task.status === "failed"
                          ? "查看并重试"
                          : "提取知识与例题"}
                </Link>
                <span className="document-date">{formatDate(document.created_at)}</span>
                <button
                  className="icon-button delete-button"
                  aria-label={`删除 ${document.filename}`}
                  onClick={() => {
                    setDeleting(document);
                    setDeleteError("");
                  }}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
          <div className="inline-info">
            <Info size={16} />
            <p>
              上传后自动提取知识点、公式和课件原有题目并存入课程知识库。点击文件名查看原始 PDF。
            </p>
          </div>
        </>
      ) : (
        <section className="document-empty">
          <span className="document-empty-icon">
            <FileText size={35} strokeWidth={1.2} />
          </span>
          <h2>暂无课件</h2>
          <button className="button secondary" onClick={() => setUploading(true)}>
            <Upload size={16} />
            选择 PDF 课件
          </button>
          <span className="empty-footnote">单个文件不超过 25 MB</span>
        </section>
      )}
      <div className="course-danger-zone">
        <div>
          <strong>课程管理</strong>
          <p>课程及其课件仅对你可见。</p>
        </div>
        <button
          className="button danger-outline"
          onClick={() => {
            setDeleting("course");
            setDeleteError("");
          }}
        >
          <Trash2 size={16} />
          删除课程
        </button>
      </div>
      {editing && (
        <CourseForm
          course={course}
          onClose={() => setEditing(false)}
          onSaved={async (result) => {
            setCourse(result);
            await refresh();
            setEditing(false);
            setSuccess("课程设置已保存");
          }}
        />
      )}
      {uploading && (
        <UploadForm
          courseId={id}
          onClose={() => setUploading(false)}
          onUploaded={async () => {
            await load();
            await refresh();
            setUploading(false);
            setSuccess("课件已保存");
          }}
        />
      )}
      {deleting && (
        <Modal
          title={deleting === "course" ? "删除这门课程？" : "删除这份课件？"}
          description={
            deleting === "course"
              ? `「${course.name}」及其全部课件、知识和问答记录将被永久删除。此操作无法撤销。`
              : `「${deleting.filename}」的原始文件和处理记录将被永久删除。`
          }
          onClose={() => setDeleting(null)}
          busy={deleteBusy}
        >
          {deleteError && <Notice message={deleteError} />}
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={deleteBusy}
              onClick={() => setDeleting(null)}
            >
              取消
            </button>
            <button
              className="button danger"
              disabled={deleteBusy}
              onClick={() => void confirmDelete()}
            >
              {deleteBusy ? "正在删除…" : "确认删除"}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
