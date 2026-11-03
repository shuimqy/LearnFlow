"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Clock3, History, RefreshCw } from "lucide-react";
import { Notice, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/http";
import { formatDate } from "@/lib/format";
import type { Task } from "@/features/tasks/types";

const statusNames: Record<string, string> = {
  pending: "等待处理",
  queued: "等待识别",
  running: "处理中",
  completed: "已完成",
  failed: "处理失败",
  cancelled: "已取消",
};

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setTasks(await api<Task[]>("/tasks"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">资料处理</div>
          <h1>
            处理记录<span className="heading-dot">.</span>
          </h1>
          <p>查看课件处理进度和失败记录。</p>
        </div>
        <button className="button secondary" disabled={loading} onClick={() => void load()}>
          <RefreshCw size={16} className={loading ? "spin" : ""} />
          刷新记录
        </button>
      </div>
      {loading ? (
        <Spinner label="正在读取处理记录" />
      ) : error ? (
        <Notice message={error} retry={() => void load()} />
      ) : !tasks.length ? (
        <section className="plain-empty task-empty">
          <History size={34} strokeWidth={1.3} />
          <h2>还没有处理记录</h2>
          <p>上传课件后，可在这里查看对应的记录。</p>
        </section>
      ) : (
        <>
          <div className="inline-info task-info">
            <Clock3 size={17} />
            <p>上传后逐页识别知识、公式和原有题目，结果自动存入对应课程的知识库。</p>
          </div>
          <div className="task-list">
            {tasks.map((task) => (
              <article className="task-row" key={task.id}>
                <span className="task-state-icon">
                  <Clock3 size={19} />
                </span>
                <div className="task-copy">
                  <h2>
                    {task.course_id ? (
                      <Link href={`/courses/${task.course_id}`}>{task.filename}</Link>
                    ) : (
                      "课件整理"
                    )}
                    <span>{task.course_name}</span>
                  </h2>
                  <p>
                    {task.error ||
                      {
                        awaiting_parser: "文件已保存，可开始识别",
                        awaiting_extraction: "文件已保存，可开始识别",
                        queued: "已加入识别队列",
                        extracting: `正在识别 · ${task.progress}%`,
                        awaiting_review: "识别已完成",
                        imported: "识别完成，已存入课程知识库",
                      }[task.stage] ||
                      task.stage}
                  </p>
                  {task.course_id && (
                    <Link
                      className="document-extraction-link"
                      href={
                        task.status === "completed"
                          ? `/courses/${task.course_id}/knowledge`
                          : `/courses/${task.course_id}/documents/${task.document_id}/extraction`
                      }
                    >
                      {task.status === "completed" ? "查看知识库" : "查看处理进度"}
                    </Link>
                  )}
                </div>
                <span className={`status-badge ${task.status === "failed" ? "failed" : "pending"}`}>
                  <span />
                  {statusNames[task.status] || task.status}
                </span>
                <time>{formatDate(task.created_at)}</time>
              </article>
            ))}
          </div>
          <p className="table-footnote">显示最近 100 条记录</p>
        </>
      )}
    </>
  );
}
