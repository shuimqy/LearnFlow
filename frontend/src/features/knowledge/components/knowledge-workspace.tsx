"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Check,
  FileText,
  History,
  MessageSquare,
  Pencil,
  Plus,
  RotateCcw,
  Search,
} from "lucide-react";
import { Modal, Notice, Spinner } from "@/components/ui";
import { Markdown } from "@/components/markdown";
import { api, errorMessage } from "@/lib/http";
import { formatDate } from "@/lib/format";
import type { Course } from "@/features/courses/types";
import type { Document } from "@/features/documents/types";
import type { KnowledgePoint, KnowledgeStats, Proposal, Revision, Snapshot } from "../types";
import { KnowledgeForm } from "./knowledge-form";
import { ProposalResult } from "./proposal-result";
import type { Chapter } from "@/features/chapters/types";
import "@/features/chapters/chapter-filter.css";
import type { ProposalProcessing } from "../types";

const operationNames: Record<string, string> = {
  create: "创建",
  update: "编辑",
  restore: "恢复",
  archive: "归档",
  correction: "确认纠错",
};
const proposalNames: Record<string, string> = {
  pending: "待确认",
  accepted: "已采纳",
  rejected: "已拒绝",
  superseded: "已过期",
};
type Action =
  | { kind: "archive" }
  | { kind: "restore"; revision: Revision }
  | { kind: "accept" | "delete_proposal"; proposal: Proposal };

export default function KnowledgeWorkspace() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const requestedPoint = params.get("point");
  const [chapterId, setChapterId] = useState(params.get("chapter") || "");
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const base = `/courses/${id}/knowledge`;
  const [course, setCourse] = useState<Course | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [points, setPoints] = useState<KnowledgePoint[]>([]);
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(requestedPoint);
  const [status, setStatus] = useState(params.get("status") === "archived" ? "archived" : "active");
  useEffect(() => {
    if (requestedPoint) {
      setSelectedId(requestedPoint);
      setTab("content");
    }
  }, [requestedPoint]);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detailsError, setDetailsError] = useState("");
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [tab, setTab] = useState("content");
  const [form, setForm] = useState<"create" | "edit" | "proposal" | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [success, setSuccess] = useState("");
  const detailRef = useRef<HTMLElement>(null);
  const layoutRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const layout = layoutRef.current;
    if (!layout) return;
    const resize = () => {
      const height = Math.max(240, window.innerHeight - layout.getBoundingClientRect().top - 20);
      layout.style.setProperty("--knowledge-panel-height", `${height}px`);
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [loading, points.length, success, error]);
  useEffect(() => {
    detailRef.current?.scrollTo({ top: 0 });
  }, [selectedId, tab]);
  const selected = useMemo(
    () => points.find((point) => point.id === selectedId) || null,
    [points, selectedId],
  );
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      setError("");
      try {
        const [nextCourse, nextDocuments, nextPoints, nextStats] = await Promise.all([
          api<Course>(`/courses/${id}`, { signal }),
          api<Document[]>(`/courses/${id}/documents`, { signal }),
          api<KnowledgePoint[]>(
            `${base}?status=${status}&q=${encodeURIComponent(search)}${chapterId ? `&chapter_id=${encodeURIComponent(chapterId)}` : ""}`,
            {
              signal,
            },
          ),
          api<KnowledgeStats>(`${base}/stats`, { signal }),
        ]);
        if (signal?.aborted) return;
        if (
          requestedPoint &&
          !search &&
          !chapterId &&
          !nextPoints.some((point) => point.id === requestedPoint)
        ) {
          const referenced = await api<KnowledgePoint>(`${base}/${requestedPoint}`, { signal });
          if (referenced.status === status) nextPoints.unshift(referenced);
        }
        if (signal?.aborted) return;
        setCourse(nextCourse);
        setDocuments(nextDocuments);
        setPoints(nextPoints);
        setStats(nextStats);
        setSelectedId((old) =>
          nextPoints.some((point) => point.id === old) ? old : nextPoints[0]?.id || null,
        );
      } catch (err) {
        if (!signal?.aborted) setError(errorMessage(err));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [base, id, status, search, requestedPoint, chapterId],
  );
  useEffect(() => {
    const controller = new AbortController();
    void api<Chapter[]>(`/courses/${id}/chapters`, { signal: controller.signal })
      .then(setChapters)
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      });
    return () => controller.abort();
  }, [id]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useEffect(() => {
    if (!selected) {
      setRevisions([]);
      setProposals([]);
      return;
    }
    let active = true;
    setDetailsLoading(true);
    setDetailsError("");
    Promise.all([
      api<Revision[]>(`${base}/${selected.id}/revisions`),
      api<Proposal[]>(`${base}/${selected.id}/proposals`),
    ])
      .then(([history, suggestions]) => {
        if (active) {
          setRevisions(history);
          setProposals(suggestions);
        }
      })
      .catch((err) => {
        if (active) setDetailsError(errorMessage(err));
      })
      .finally(() => {
        if (active) setDetailsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [base, selected]);
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(""), 5000);
    return () => clearTimeout(timer);
  }, [success]);
  async function confirmAction() {
    if (!action || !selected) return;
    setActionBusy(true);
    setActionError("");
    let processing: ProposalProcessing | undefined;
    try {
      if (action.kind === "archive") {
        await api(`${base}/${selected.id}?expected_version=${selected.version}`, {
          method: "DELETE",
        });
      } else if (action.kind === "restore") {
        await api(`${base}/${selected.id}/restore`, {
          method: "POST",
          body: JSON.stringify({
            revision_id: action.revision.id,
            expected_version: selected.version,
            reason: `恢复到第 ${action.revision.version} 版`,
          }),
        });
      } else if (action.kind === "delete_proposal") {
        await api(`${base}/${selected.id}/proposals/${action.proposal.id}`, { method: "DELETE" });
      } else {
        const result = await api<KnowledgePoint & { processing?: ProposalProcessing }>(
          `${base}/${selected.id}/proposals/${action.proposal.id}/${action.kind}`,
          {
            method: "POST",
            body: JSON.stringify({ expected_version: selected.version }),
          },
        );
        processing = result.processing;
      }
      const message =
        action.kind === "archive"
          ? "知识点已归档，不再参与检索"
          : action.kind === "delete_proposal"
            ? "修改建议已删除"
            : processing?.message || "知识已更新，修订记录已保存";
      setAction(null);
      if (action.kind === "restore" && status === "archived") setStatus("active");
      else await load();
      if (action.kind === "accept") setTab("proposals");
      setSuccess(message);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setActionBusy(false);
    }
  }
  function beginAction(next: Action) {
    setAction(next);
    setActionError("");
  }
  const pending = proposals.filter((item) => item.status === "pending");
  if (!course && loading) return <Spinner label="正在读取课程知识库" />;
  if (!course && error) return <Notice message={error} retry={() => void load()} />;
  return (
    <>
      <Link className="back-link" href={`/courses/${id}`}>
        <ArrowLeft size={15} />
        返回课程课件
      </Link>
      <div className="page-heading knowledge-page-heading">
        <div>
          <div className="eyebrow">{course?.name}</div>
          <h1>
            课程知识库<span className="heading-dot">.</span>
          </h1>
          <p>整理、修订和查找这门课的知识。内容仅在当前课程内检索。</p>
        </div>
        <div className="knowledge-heading-actions">
          <Link href={`/courses/${id}/chat`} className="button secondary">
            <MessageSquare size={15} />
            课程问答
          </Link>
          <button className="button primary" onClick={() => setForm("create")}>
            <Plus size={16} />
            添加知识点
          </button>
        </div>
      </div>
      <div className="knowledge-toolbar">
        <label className="knowledge-chapter-filter">
          章节
          <select
            aria-label="知识点章节"
            value={chapterId}
            onChange={(event) => setChapterId(event.target.value)}
          >
            <option value="">全部章节</option>
            {chapters.map((chapter) => (
              <option key={chapter.id} value={chapter.id}>
                {chapter.title} · {chapter.filename}
              </option>
            ))}
          </select>
        </label>
        <div className="knowledge-status-tabs">
          <button
            className={status === "active" ? "selected" : ""}
            onClick={() => setStatus("active")}
          >
            知识点 <span>{stats?.active || 0}</span>
          </button>
          <button
            className={status === "archived" ? "selected" : ""}
            onClick={() => setStatus("archived")}
          >
            已归档 <span>{stats?.archived || 0}</span>
          </button>
        </div>
        <label className="search-field">
          <Search size={15} />
          <input
            aria-label="搜索知识点"
            placeholder="按标题和正文查找…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>
      {success && (
        <div className="success-notice" role="status">
          <Check size={15} />
          {success}
        </div>
      )}
      {error && <Notice message={error} retry={() => void load()} />}
      {loading ? (
        <Spinner label="正在读取知识点" />
      ) : !points.length ? (
        <div className="plain-empty knowledge-empty">
          <BookOpen size={35} strokeWidth={1.3} />
          <h2>
            {query
              ? "没有找到相关知识点"
              : status === "archived"
                ? "没有已归档的知识点"
                : "暂无知识点"}
          </h2>
          <p>
            {query
              ? "换个关键词，或清空搜索再看看。"
              : status === "archived"
                ? "归档后的内容可在这里查看和恢复。"
                : "上传课件后会自动整理知识和原有题目，也可以手动添加笔记并关联课件页码。"}
          </p>
          {!query && status === "active" && (
            <button className="button secondary" onClick={() => setForm("create")}>
              <Plus size={15} />
              添加第一个知识点
            </button>
          )}
        </div>
      ) : (
        <div className="knowledge-layout" ref={layoutRef}>
          <aside className="knowledge-list" aria-label="知识点列表" tabIndex={0}>
            {points.map((point) => (
              <button
                key={point.id}
                className={`knowledge-list-item ${selectedId === point.id ? "selected" : ""}`}
                onClick={() => {
                  setSelectedId(point.id);
                  setTab("content");
                }}
              >
                <span className="knowledge-list-title">{point.title}</span>
                <span className="knowledge-list-summary">
                  {point.summary || point.content.slice(0, 70)}
                </span>
                <span className="knowledge-list-meta">
                  第 {point.version} 版 ·{" "}
                  {point.sources.length ? `${point.sources.length} 处引用` : "独立笔记"}
                </span>
              </button>
            ))}
            {points.length >= 200 && (
              <p className="table-footnote">显示前 200 条，请搜索定位更多内容。</p>
            )}
          </aside>
          {selected && (
            <section
              className="knowledge-detail"
              ref={detailRef}
              aria-label="知识点详情"
              tabIndex={0}
            >
              <div className="knowledge-detail-header">
                <div>
                  <span className="small-label">
                    {selected.status === "active" ? "课程知识" : "已归档"} / 第 {selected.version}{" "}
                    版
                  </span>
                  <h2>{selected.title}</h2>
                </div>
                {selected.status === "active" && (
                  <button className="button secondary" onClick={() => setForm("edit")}>
                    <Pencil size={14} />
                    编辑
                  </button>
                )}
              </div>
              <div className="knowledge-detail-tabs">
                <button
                  className={tab === "content" ? "selected" : ""}
                  onClick={() => setTab("content")}
                >
                  <FileText size={14} />
                  正文
                </button>
                <button
                  className={tab === "history" ? "selected" : ""}
                  onClick={() => setTab("history")}
                >
                  <History size={14} />
                  修订记录
                </button>
                <button
                  className={tab === "proposals" ? "selected" : ""}
                  onClick={() => setTab("proposals")}
                >
                  <MessageSquare size={14} />
                  修改建议{pending.length > 0 && <span>{pending.length}</span>}
                </button>
              </div>
              {detailsError && <Notice message={detailsError} retry={() => void load()} />}
              {tab === "content" && (
                <>
                  <div className="knowledge-body">
                    {selected.summary && <p className="knowledge-summary">{selected.summary}</p>}
                    <div className="knowledge-prose">
                      <Markdown>{selected.content}</Markdown>
                    </div>
                  </div>
                  <div className="knowledge-references">
                    <h3>来源引用</h3>
                    {selected.sources.length ? (
                      selected.sources.map((source) => (
                        <div className="knowledge-reference" key={source.id}>
                          <div>
                            <FileText size={14} />
                            {source.document_id ? (
                              <a
                                href={`/api/documents/${source.document_id}/file#page=${source.page_number}`}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {source.filename} · 第 {source.page_number} 页
                                <ArrowUpRight size={12} />
                              </a>
                            ) : (
                              <span>
                                {source.filename} · 第 {source.page_number} 页（原文件已删除）
                              </span>
                            )}
                          </div>
                          {source.quote && (
                            <details>
                              <summary>查看引用原文</summary>
                              <blockquote>{source.quote}</blockquote>
                            </details>
                          )}
                        </div>
                      ))
                    ) : (
                      <p>独立笔记，尚未关联课件。</p>
                    )}
                  </div>
                  <div className="knowledge-detail-footer">
                    <span>{formatDate(selected.updated_at)} 更新</span>
                    {selected.status === "active" && (
                      <div>
                        <button className="text-button" onClick={() => setForm("proposal")}>
                          提出修改建议
                        </button>
                        <button
                          className="text-button danger-text"
                          onClick={() => beginAction({ kind: "archive" })}
                        >
                          <Archive size={13} />
                          归档
                        </button>
                      </div>
                    )}
                  </div>
                </>
              )}
              {tab === "history" &&
                (detailsLoading ? (
                  <Spinner label="正在读取修订记录" />
                ) : (
                  <div className="revision-list">
                    {revisions.map((revision) => (
                      <article className="revision-card" key={revision.id}>
                        <div className="revision-heading">
                          <strong>第 {revision.version} 版</strong>
                          <span>
                            {operationNames[revision.operation] || revision.operation} ·{" "}
                            {formatDate(revision.created_at)}
                          </span>
                        </div>
                        <p>{revision.reason}</p>
                        <details>
                          <summary>查看这一版内容</summary>
                          <SnapshotView value={revision.snapshot} />
                        </details>
                        {(revision.version !== selected.version ||
                          selected.status === "archived") && (
                          <button
                            className="text-button"
                            onClick={() => beginAction({ kind: "restore", revision })}
                          >
                            <RotateCcw size={12} />
                            恢复此版本
                          </button>
                        )}
                      </article>
                    ))}
                  </div>
                ))}
              {tab === "proposals" &&
                (detailsLoading ? (
                  <Spinner label="正在读取修改建议" />
                ) : (
                  <div className="proposal-list">
                    {!proposals.length ? (
                      <div className="plain-empty">
                        <MessageSquare size={27} strokeWidth={1.4} />
                        <h2>还没有修改建议</h2>
                        <p>建议会先保留在这里，确认后再更新知识。</p>
                        {selected.status === "active" && (
                          <button className="button secondary" onClick={() => setForm("proposal")}>
                            提出修改建议
                          </button>
                        )}
                      </div>
                    ) : (
                      proposals.map((proposal) => (
                        <article className="proposal-card" key={proposal.id}>
                          <div className="revision-heading">
                            <strong>{proposal.proposed.title}</strong>
                            <span>{proposalNames[proposal.status]}</span>
                          </div>
                          <p>{proposal.reason}</p>
                          <span className="field-hint">
                            基于第 {proposal.base_version} 版 · {formatDate(proposal.created_at)}
                          </span>
                          {proposal.processing && (
                            <p className="field-hint">模型正在审查并处理，请稍后刷新查看。</p>
                          )}
                          {proposal.llm_review && <ProposalResult result={proposal.llm_review} />}
                          <div className="proposal-actions">
                            {proposal.status === "pending" && (
                              <button
                                className="button secondary"
                                disabled={proposal.processing}
                                onClick={() => beginAction({ kind: "accept", proposal })}
                              >
                                交由模型处理
                              </button>
                            )}
                            <button
                              className="text-button danger-text"
                              disabled={proposal.processing}
                              onClick={() => beginAction({ kind: "delete_proposal", proposal })}
                            >
                              删除
                            </button>
                          </div>
                        </article>
                      ))
                    )}
                  </div>
                ))}
            </section>
          )}
        </div>
      )}
      <p className="knowledge-scope-note">列表支持关键词查找，自然语言提问可进入课程问答。</p>
      {form && (
        <KnowledgeForm
          courseId={id}
          point={form === "create" ? undefined : selected || undefined}
          documents={documents}
          mode={form}
          onClose={() => setForm(null)}
          onSaved={async (pointId, proposal) => {
            setForm(null);
            setSelectedId(pointId);
            if (search || status !== "active") {
              setQuery("");
              setSearch("");
              setStatus("active");
            } else await load();
            setSuccess(
              proposal ? "修改建议已保存，可交由模型审查并处理" : "知识点已保存，检索内容已同步",
            );
            if (proposal) setTab("proposals");
          }}
        />
      )}
      {action && selected && (
        <Modal
          title={
            action.kind === "archive"
              ? "归档这个知识点？"
              : action.kind === "restore"
                ? "恢复历史版本？"
                : action.kind === "delete_proposal"
                  ? "删除这条修改建议？"
                  : "交由模型处理修改建议"
          }
          description={
            action.kind === "archive"
              ? "归档后不再参与检索，历史版本和引用会保留，可以恢复。"
              : action.kind === "delete_proposal"
                ? "删除这条建议及其模型处理结果。知识正文和已有修订记录会保留。"
                : action.kind === "accept"
                  ? "模型将结合修改原因和课件来源审查建议。支持的修改会保存为新版本，依据不足或不合理时保留原文，并返回意见与处理结果。"
                  : "确认后保存为一个新版本，并同步更新检索内容。"
          }
          onClose={() => setAction(null)}
          busy={actionBusy}
          wide={action.kind === "accept" || action.kind === "restore"}
        >
          {(action.kind === "accept" || action.kind === "restore") && (
            <div className="knowledge-comparison">
              <div>
                <h3>当前内容 · 第 {selected.version} 版</h3>
                <SnapshotView value={selected} />
              </div>
              <div>
                <h3>
                  {action.kind === "restore"
                    ? `恢复第 ${action.revision.version} 版的内容`
                    : "建议内容"}
                </h3>
                <SnapshotView
                  value={
                    action.kind === "restore" ? action.revision.snapshot : action.proposal.proposed
                  }
                />
              </div>
            </div>
          )}
          {actionError && <Notice message={actionError} />}
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={actionBusy}
              onClick={() => setAction(null)}
            >
              取消
            </button>
            <button
              className={`button ${action.kind === "archive" || action.kind === "delete_proposal" ? "danger" : "primary"}`}
              disabled={actionBusy}
              onClick={() => void confirmAction()}
            >
              {actionBusy
                ? action.kind === "accept"
                  ? "模型正在审查并处理…"
                  : "正在保存…"
                : action.kind === "archive"
                  ? "确认归档"
                  : action.kind === "restore"
                    ? "确认恢复"
                    : action.kind === "delete_proposal"
                      ? "确认删除"
                      : "确认交由模型处理"}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function SnapshotView({ value }: { value: Snapshot }) {
  return (
    <div className="snapshot-view">
      <strong>{value.title}</strong>
      {value.summary && <p>{value.summary}</p>}
      <Markdown>{value.content}</Markdown>
      {value.sources.length > 0 && (
        <div className="snapshot-sources">
          {value.sources.map((source, index) => (
            <div key={index}>
              <span>
                {source.filename} · 第 {source.page_number} 页
              </span>
              {source.quote && <blockquote>{source.quote}</blockquote>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
