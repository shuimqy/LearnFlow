"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowUp, Download, Plus, Save, Trash2 } from "lucide-react";
import { Markdown } from "@/components/markdown";
import { MarkdownEditor } from "@/components/markdown-editor";
import { Modal, Notice, Spinner } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/http";
import type { Course } from "@/features/courses/types";
import type { Document } from "@/features/documents/types";
import type { Exercise, Workbook, WorkbookSummary } from "../types";
import "../workbook.css";
import type { Chapter } from "@/features/chapters/types";
import { WorkbookSources, type WorkbookScope } from "./workbook-sources";
import { AutomaticAssembly, typeLabels, difficultyLabels } from "./automatic-assembly";
import { ExerciseCropEditor } from "./exercise-crop-editor";

function emptyBook(courseId: string, title = "课件做题本"): Workbook {
  return {
    id: "",
    course_id: courseId,
    title,
    version: 0,
    updated_at: "",
    sections: [{ title: "习题", items: [] }],
    settings: { include_answers: true, answer_space: "medium", show_sources: true },
  };
}

export default function WorkbookWorkspace() {
  const { id } = useParams<{ id: string }>();
  const base = `/courses/${id}`;
  const [course, setCourse] = useState<Course | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [saved, setSaved] = useState<WorkbookSummary[]>([]);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [scope, setScope] = useState<WorkbookScope>({
    document_ids: [],
    chapter_ids: [],
    page_from: "",
    page_to: "",
  });
  const [dataRevision, setDataRevision] = useState(0);
  const changedStructure = useCallback(() => setDataRevision((value) => value + 1), []);
  const [cropItem, setCropItem] = useState<Exercise | null>(null);
  const [pendingDraft, setPendingDraft] = useState<Pick<
    Workbook,
    "title" | "sections" | "settings"
  > | null>(null);
  const [book, setBook] = useState<Workbook>(() => emptyBook(id));
  const [dirty, setDirty] = useState(false);
  const [activeGroup, setActiveGroup] = useState(0);
  const [candidates, setCandidates] = useState<{ total: number; items: Exercise[] }>({
    total: 0,
    items: [],
  });
  const [kind, setKind] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [finding, setFinding] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [findError, setFindError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [editing, setEditing] = useState<{ group: number; index: number; item: Exercise } | null>(
    null,
  );
  const [switchTarget, setSwitchTarget] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const scopeQuery = useMemo(() => {
    const params = new URLSearchParams();
    scope.document_ids.forEach((key) => params.append("document_ids", key));
    scope.chapter_ids.forEach((key) => params.append("chapter_ids", key));
    if (scope.page_from) params.set("page_from", scope.page_from);
    if (scope.page_to) params.set("page_to", scope.page_to);
    return params.toString();
  }, [scope]);
  const chapterRevision = JSON.stringify(chapters);
  const scopeError = !scope.document_ids.length
    ? "请先选择来源课件。"
    : scope.chapter_ids.some(
          (id) =>
            !chapters.some(
              (chapter) => chapter.id === id && scope.document_ids.includes(chapter.document_id),
            ),
        )
      ? "所选章节已变更，请清除章节限制后重新选择。"
      : [scope.page_from, scope.page_to].some(
            (page) => page && (!Number.isInteger(Number(page)) || Number(page) < 1),
          ) ||
          (scope.page_from && scope.page_to && Number(scope.page_from) > Number(scope.page_to))
        ? "请填写有效页码，且起始页不能大于结束页。"
        : "";
  const validScope = !scopeError;
  const count = book.sections.reduce((sum, group) => sum + group.items.length, 0);
  const selected = new Set(
    book.sections.flatMap((group) => group.items.map((item) => item.draft_id)),
  );

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError("");
      try {
        const [nextCourse, nextDocuments, nextSaved] = await Promise.all([
          api<Course>(base, { signal }),
          api<Document[]>(`${base}/documents`, { signal }),
          api<WorkbookSummary[]>(`${base}/workbooks`, { signal }),
        ]);
        if (signal?.aborted) return;
        setCourse(nextCourse);
        setDocuments(nextDocuments);
        setScope({
          document_ids: nextDocuments.map((doc) => doc.id),
          chapter_ids: [],
          page_from: "",
          page_to: "",
        });
        setSaved(nextSaved);
        setBook(emptyBook(id, `${nextCourse.name} · 做题本`));
        setDirty(false);
      } catch (err) {
        if (!signal?.aborted) setError(errorMessage(err));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [base, id],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useEffect(() => {
    let controller: AbortController;
    function refreshChapters() {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      void api<Chapter[]>(`${base}/chapters`, { signal: current.signal })
        .then((next) => {
          if (!current.signal.aborted) setChapters(next);
        })
        .catch((err) => {
          if (!current.signal.aborted) setError(errorMessage(err));
        });
    }
    refreshChapters();
    window.addEventListener("focus", refreshChapters);
    return () => {
      controller?.abort();
      window.removeEventListener("focus", refreshChapters);
    };
  }, [base, dataRevision]);
  useEffect(() => {
    const controller = new AbortController();
    if (!validScope) {
      setCandidates({ total: 0, items: [] });
      setFinding(false);
      setFindError(scopeError);
      return () => controller.abort();
    }
    setFinding(true);
    setFindError("");
    void api<{ total: number; items: Exercise[] }>(
      `${base}/exercises?${scopeQuery}&${filter}&offset=${offset}&limit=20`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) setCandidates(result);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setFindError(errorMessage(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setFinding(false);
      });
    return () => controller.abort();
  }, [base, filter, offset, dataRevision, scopeQuery, validScope, scopeError, chapterRevision]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function change(next: Workbook) {
    setBook(next);
    setDirty(true);
    setFeedback("");
  }
  function applyDraft(result: Pick<Workbook, "title" | "sections" | "settings">) {
    change({ ...emptyBook(id), ...result });
    setActiveGroup(0);
    setPendingDraft(null);
  }
  function assetUrl(item: Exercise, assetId: string) {
    return item.asset_scope === "workbook"
      ? `/api${base}/workbooks/${book.id}/assets/${assetId}`
      : `/api${base}/exercises/${item.draft_id}/assets/${assetId}`;
  }
  async function refreshCrop(item: Exercise) {
    changedStructure();
    try {
      const fresh = await api<Exercise>(`${base}/exercises/${item.draft_id}`);
      setBook((old) => ({
        ...old,
        sections: old.sections.map((group) => ({
          ...group,
          items: group.items.map((row) =>
            row.draft_id === fresh.draft_id
              ? {
                  ...fresh,
                  title: row.title,
                  question: row.question,
                  answer: row.answer,
                  solution: row.solution,
                }
              : row,
          ),
        })),
      }));
      if (selected.has(item.draft_id)) setDirty(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  function toggleExercise(item: Exercise) {
    if (selected.has(item.draft_id)) {
      change({
        ...book,
        sections: book.sections.map((group) => ({
          ...group,
          items: group.items.filter((row) => row.draft_id !== item.draft_id),
        })),
      });
    } else if (count >= 100) {
      setError("每本最多 100 题，请新建另一本。");
    } else {
      change({
        ...book,
        sections: book.sections.map((group, index) =>
          index === activeGroup ? { ...group, items: [...group.items, item] } : group,
        ),
      });
    }
  }
  function moveItem(groupIndex: number, index: number, direction: number) {
    const sections = book.sections.map((group) => ({ ...group, items: [...group.items] }));
    const items = sections[groupIndex].items;
    [items[index], items[index + direction]] = [items[index + direction], items[index]];
    change({ ...book, sections });
  }
  function moveGroup(index: number, direction: number) {
    const sections = [...book.sections];
    [sections[index], sections[index + direction]] = [sections[index + direction], sections[index]];
    change({ ...book, sections });
    setActiveGroup(index + direction);
  }
  async function openBook(target: string) {
    setSwitchTarget(null);
    setBusy(true);
    setError("");
    try {
      const next = target
        ? await api<Workbook>(`${base}/workbooks/${target}`)
        : emptyBook(id, `${course?.name} · 做题本`);
      setBook(next);
      setDirty(false);
      setActiveGroup(0);
      setFeedback("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  function requestOpen(target: string) {
    if (dirty) setSwitchTarget(target);
    else void openBook(target);
  }
  async function persist(): Promise<Workbook> {
    if (book.id && !dirty) return book;
    if (
      !book.title.trim() ||
      !count ||
      book.sections.some((group) => group.items.length && !group.title.trim())
    ) {
      throw new Error("请填写做题本及分组名称，并至少选择一道题。");
    }
    const result = await api<Workbook>(`${base}/workbooks${book.id ? `/${book.id}` : ""}`, {
      method: book.id ? "PUT" : "POST",
      body: JSON.stringify({
        ...book,
        expected_version: book.version,
        sections: book.sections.filter((group) => group.items.length),
      }),
    });
    setBook(result);
    setDirty(false);
    setActiveGroup(0);
    setSaved((previous) => [result, ...previous.filter((item) => item.id !== result.id)]);
    return result;
  }
  async function saveOrExport(download: boolean) {
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const result = await persist();
      if (download) {
        const response = await fetch(
          `/api${base}/workbooks/${result.id}/pdf?version=${result.version}`,
          { credentials: "same-origin", cache: "no-store" },
        );
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new ApiError(response.status, body?.detail || "PDF 导出失败，请稍后重试。");
        }
        const url = URL.createObjectURL(await response.blob());
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${result.title.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")}.pdf`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        setFeedback("PDF 已生成，做题本已保存。");
      } else {
        setFeedback("做题本已保存。");
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function renameBook() {
    if (!book.id || !book.title.trim()) return;
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const result = await api<Workbook>(`${base}/workbooks/${book.id}/title`, {
        method: "PATCH",
        body: JSON.stringify({ title: book.title, expected_version: book.version }),
      });
      setDirty(
        JSON.stringify([book.sections, book.settings]) !==
          JSON.stringify([result.sections, result.settings]),
      );
      setBook({
        ...book,
        title: result.title,
        version: result.version,
        updated_at: result.updated_at,
      });
      setSaved((previous) => previous.map((row) => (row.id === result.id ? result : row)));
      setFeedback("做题本名称已保存。");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function deleteBook() {
    setBusy(true);
    setError("");
    try {
      await api(`${base}/workbooks/${book.id}`, { method: "DELETE" });
      setSaved((previous) => previous.filter((item) => item.id !== book.id));
      setBook(emptyBook(id, `${course?.name} · 做题本`));
      setDirty(false);
      setActiveGroup(0);
      setDeleteOpen(false);
    } catch (err) {
      setError(errorMessage(err));
      setDeleteOpen(false);
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <Spinner label="正在读取做题本" />;
  if (!course) return <Notice message={error || "课程不存在"} retry={() => void load()} />;
  return (
    <>
      <Link className="back-link" href={base}>
        <ArrowLeft size={15} />
        {course.name}
      </Link>
      <div className="page-heading workbook-heading">
        <div>
          <h1>课件做题本</h1>
          <p>从课件原题中挑选，按章节或学习任务分组，整理后打印练习。</p>
        </div>
      </div>
      {error && <Notice message={error} />}
      {feedback && (
        <p className="success-notice" role="status">
          {feedback}
        </p>
      )}
      <div className="workbook-bar">
        <label>
          已保存的做题本
          <select
            aria-label="已保存的做题本"
            value={book.id}
            disabled={busy}
            onChange={(event) => requestOpen(event.target.value)}
          >
            <option value="">新做题本</option>
            {saved.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <button className="button secondary" disabled={busy} onClick={() => requestOpen("")}>
          <Plus size={16} />
          新建
        </button>
        <span className="workbook-save-state">
          {dirty ? "有未保存的修改" : book.id ? "已保存" : "尚未保存"}
        </span>
      </div>
      <form
        className="workbook-name-form"
        onSubmit={(event) => {
          event.preventDefault();
          void renameBook();
        }}
      >
        <label>
          做题本名称
          <input
            aria-label="做题本名称"
            value={book.title}
            maxLength={160}
            required
            disabled={busy}
            onChange={(event) => change({ ...book, title: event.target.value })}
          />
        </label>
        {book.id ? (
          <button
            className="button secondary"
            disabled={
              busy ||
              !book.title.trim() ||
              book.title.trim() === saved.find((row) => row.id === book.id)?.title
            }
          >
            <Save size={15} />
            保存名称
          </button>
        ) : (
          <span className="workbook-note">新题本的名称会在保存题目时一起保存。</span>
        )}
      </form>
      <WorkbookSources
        courseId={id}
        documents={documents}
        chapters={chapters}
        scope={scope}
        disabled={busy}
        onChange={(next) => {
          setScope(next);
          setOffset(0);
        }}
      />
      <AutomaticAssembly
        courseId={id}
        scope={scope}
        sourceRevision={`${dataRevision}:${chapterRevision}`}
        disabled={busy || !validScope}
        onApply={(result) => {
          if (dirty) setPendingDraft(result);
          else applyDraft(result);
        }}
      />
      <p className="workbook-note">
        可按已识别章节或页码选题。原题保真版使用已确认裁片；文字重排版附已确认的题图。题目和答案来自原始识别，请核对提示。
      </p>
      <div className="workbook-layout">
        <section className="workbook-picker" aria-label="课件题目">
          <h2 id="workbook-picker" tabIndex={-1}>
            2. 手动选择原题
          </h2>
          <p className="workbook-note">
            当前使用上方所选课件和范围。勾选题目加入本册，也可以先用“按要求自动整理做题本”生成草稿。
          </p>
          <form
            className="workbook-filters"
            onSubmit={(event) => {
              event.preventDefault();
              const params = new URLSearchParams();
              if (kind) params.set("kind", kind);
              if (query.trim()) params.set("query", query.trim());
              setFilter(params.toString());
              setOffset(0);
            }}
          >
            <label>
              题目类型
              <select value={kind} onChange={(event) => setKind(event.target.value)}>
                <option value="">习题与例题</option>
                <option value="exercise">只看习题</option>
                <option value="worked_example">只看例题</option>
              </select>
            </label>
            <label>
              标题关键词
              <input
                value={query}
                maxLength={100}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <button className="button secondary workbook-full" disabled={finding}>
              筛选题目
            </button>
          </form>
          <label className="workbook-target">
            勾选后加入分组
            <select
              aria-label="加入分组"
              value={activeGroup}
              disabled={busy}
              onChange={(event) => setActiveGroup(Number(event.target.value))}
            >
              {book.sections.map((group, i) => (
                <option key={i} value={i}>
                  {group.title || `第 ${i + 1} 组`}
                </option>
              ))}
            </select>
          </label>
          {findError ? (
            <Notice message={findError} />
          ) : finding ? (
            <Spinner label="正在查找题目" />
          ) : (
            <>
              <div className="workbook-result-count">找到 {candidates.total} 道课件题目</div>
              {!candidates.total && (
                <p className="workbook-empty">
                  当前范围内没有题目。可调整页码，或在课程资料页检查课件识别是否完成。
                </p>
              )}
              <div className="workbook-candidates">
                {candidates.items.map((item) => (
                  <article
                    className={`workbook-candidate ${selected.has(item.draft_id) ? "is-selected" : ""}`}
                    key={item.draft_id}
                  >
                    <label className="workbook-pick-title">
                      <input
                        type="checkbox"
                        checked={selected.has(item.draft_id)}
                        disabled={busy || (!selected.has(item.draft_id) && count >= 100)}
                        onChange={() => toggleExercise(item)}
                      />
                      <strong>{item.title}</strong>
                    </label>
                    <div className="workbook-source">
                      {item.kind === "exercise" ? "习题" : "例题"} · {item.filename} · 第{" "}
                      {item.page_number} 页{" "}
                      <a
                        href={`/api/documents/${item.document_id}/file#page=${item.page_number}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        原页
                      </a>
                    </div>
                    <div className="workbook-question-preview">
                      <Markdown>{item.question}</Markdown>
                    </div>
                    <p className="workbook-source">
                      {item.chapter?.title || "未分章"} ·{" "}
                      {typeLabels[item.question_type || "other"]} ·{" "}
                      {difficultyLabels[item.difficulty || "unknown"]}
                      {item.difficulty && item.difficulty !== "unknown" ? "（估计）" : ""}
                    </p>
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => setCropItem(item)}
                    >
                      {item.crop_status === "confirmed" ? "查看裁片与标签" : "核对裁片与标签"}
                    </button>
                    {item.warnings.length > 0 && (
                      <details className="workbook-warnings">
                        <summary>{item.warnings.length} 条识别或修订提示</summary>
                        {item.warnings.map((warning, i) => (
                          <p key={i}>{warning}</p>
                        ))}
                        <Link href={`${base}/knowledge?point=${item.knowledge_id}`}>
                          查看知识库
                        </Link>
                      </details>
                    )}
                  </article>
                ))}
              </div>
              {candidates.total > 20 && (
                <div className="workbook-pagination">
                  <button
                    className="button secondary"
                    disabled={!offset}
                    onClick={() => setOffset((value) => value - 20)}
                  >
                    上一页
                  </button>
                  <span>
                    {offset + 1}–{Math.min(offset + 20, candidates.total)}
                  </span>
                  <button
                    className="button secondary"
                    disabled={offset + 20 >= candidates.total}
                    onClick={() => setOffset((value) => value + 20)}
                  >
                    下一页
                  </button>
                </div>
              )}
            </>
          )}
        </section>
        <section className="workbook-editor" aria-label="做题本内容">
          <fieldset disabled={busy} className="workbook-editor-fields">
            <div className="workbook-editor-heading">
              <h2>
                3. 编辑并导出 <span>{count} / 100 题</span>
              </h2>
              <button
                type="button"
                className="text-button danger-text"
                disabled={!book.id}
                onClick={() => setDeleteOpen(true)}
              >
                <Trash2 size={14} />
                删除本册
              </button>
            </div>
            <div className="workbook-print-settings">
              <label>
                打印方式
                <select
                  aria-label="打印方式"
                  value={book.settings.print_mode || "text"}
                  onChange={(event) =>
                    change({
                      ...book,
                      settings: {
                        ...book.settings,
                        print_mode: event.target.value as "text" | "original",
                      },
                    })
                  }
                >
                  <option value="text">文字重排（附题图）</option>
                  <option value="original">原题保真（裁片）</option>
                </select>
              </label>
              <label>
                每题答题空间
                <select
                  value={book.settings.answer_space}
                  onChange={(event) =>
                    change({
                      ...book,
                      settings: {
                        ...book.settings,
                        answer_space: event.target.value as Workbook["settings"]["answer_space"],
                      },
                    })
                  }
                >
                  <option value="compact">少量留白</option>
                  <option value="medium">标准留白</option>
                  <option value="large">较多留白</option>
                  <option value="page">每题另起一页</option>
                </select>
              </label>
              <label className="workbook-check">
                <input
                  type="checkbox"
                  checked={book.settings.include_answers}
                  onChange={(event) =>
                    change({
                      ...book,
                      settings: { ...book.settings, include_answers: event.target.checked },
                    })
                  }
                />
                末尾附答案与解析
              </label>
              <label className="workbook-check">
                <input
                  type="checkbox"
                  checked={book.settings.show_sources}
                  onChange={(event) =>
                    change({
                      ...book,
                      settings: { ...book.settings, show_sources: event.target.checked },
                    })
                  }
                />
                打印课件名和页码
              </label>
            </div>
            <p className="workbook-note">
              这里保存独立副本，修改题干、答案或排序不会改动知识库。
              {book.settings.print_mode === "original" &&
                "保真版按原题裁片打印；题干文字编辑只影响文字重排版。未确认裁片的题目会阻止保真导出。"}
            </p>
            {book.sections.map((group, gi) => (
              <section className="workbook-group" aria-label={`分组 ${gi + 1}`} key={gi}>
                <div className="workbook-group-heading">
                  <label>
                    章节 / 分组名称
                    <input
                      value={group.title}
                      maxLength={160}
                      onChange={(event) =>
                        change({
                          ...book,
                          sections: book.sections.map((row, i) =>
                            i === gi ? { ...row, title: event.target.value } : row,
                          ),
                        })
                      }
                    />
                  </label>
                  <button
                    className="icon-button"
                    aria-label={`上移分组 ${gi + 1}`}
                    disabled={!gi}
                    onClick={() => moveGroup(gi, -1)}
                  >
                    <ArrowUp size={16} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`下移分组 ${gi + 1}`}
                    disabled={gi === book.sections.length - 1}
                    onClick={() => moveGroup(gi, 1)}
                  >
                    <ArrowDown size={16} />
                  </button>
                  {!group.items.length && book.sections.length > 1 && (
                    <button
                      className="icon-button"
                      aria-label={`删除空分组 ${gi + 1}`}
                      onClick={() => {
                        change({ ...book, sections: book.sections.filter((_, i) => i !== gi) });
                        setActiveGroup(0);
                      }}
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                </div>
                {!group.items.length && (
                  <p className="workbook-empty">在左侧选择此分组，再勾选需要的题目。</p>
                )}
                {group.items.map((item, index) => (
                  <article className="workbook-selected" key={item.draft_id}>
                    <div className="workbook-selected-heading">
                      <strong>
                        {book.sections
                          .slice(0, gi)
                          .reduce((sum, row) => sum + row.items.length, 0) +
                          index +
                          1}
                        . {item.title}
                      </strong>
                      <div>
                        <button
                          className="icon-button"
                          aria-label={`上移 ${item.title}`}
                          disabled={!index}
                          onClick={() => moveItem(gi, index, -1)}
                        >
                          <ArrowUp size={15} />
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`下移 ${item.title}`}
                          disabled={index === group.items.length - 1}
                          onClick={() => moveItem(gi, index, 1)}
                        >
                          <ArrowDown size={15} />
                        </button>
                        <button
                          className="text-button"
                          onClick={() => setEditing({ group: gi, index, item: { ...item } })}
                        >
                          编辑题目
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`移除 ${item.title}`}
                          onClick={() => toggleExercise(item)}
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </div>
                    <div className="workbook-source">
                      {item.filename} · 第 {item.page_number} 页
                    </div>
                    <Markdown>{item.question}</Markdown>
                    {(item.assets || [])
                      .filter((asset) => asset.role === "figure")
                      .map((asset) => (
                        <img
                          className="workbook-crop-preview"
                          key={asset.id}
                          src={assetUrl(item, asset.id)}
                          alt={`${item.title}题图`}
                        />
                      ))}
                    <details>
                      <summary>
                        原题裁片{item.crop_status !== "confirmed" ? "（尚未确认）" : ""}
                      </summary>
                      {(item.assets || [])
                        .filter((asset) => asset.role === "question")
                        .map((asset) => (
                          <img
                            className="workbook-crop-preview"
                            key={asset.id}
                            src={assetUrl(item, asset.id)}
                            alt={`${item.title}原题裁片`}
                          />
                        ))}
                      {documents.some((document) => document.id === item.document_id) && (
                        <button className="text-button" onClick={() => setCropItem(item)}>
                          调整裁片与标签
                        </button>
                      )}
                    </details>
                    <details>
                      <summary>
                        答案与解析{!item.answer && !item.solution ? "（课件未提供）" : ""}
                      </summary>
                      <Markdown>{item.answer || "课件未提供答案。"}</Markdown>
                      <Markdown>{item.solution || "课件未提供解题步骤。"}</Markdown>
                    </details>
                    {item.warnings.length > 0 && (
                      <details className="workbook-warnings">
                        <summary>查看识别或修订提示（保留在 PDF 中）</summary>
                        {item.warnings.map((warning, i) => (
                          <p key={i}>{warning}</p>
                        ))}
                      </details>
                    )}
                    {book.sections.length > 1 && (
                      <label className="workbook-move-to">
                        移至分组
                        <select
                          aria-label={`移动 ${item.title} 到分组`}
                          value={gi}
                          onChange={(event) => {
                            const target = Number(event.target.value);
                            change({
                              ...book,
                              sections: book.sections.map((row, i) =>
                                i === gi
                                  ? {
                                      ...row,
                                      items: row.items.filter(
                                        (entry) => entry.draft_id !== item.draft_id,
                                      ),
                                    }
                                  : i === target
                                    ? { ...row, items: [...row.items, item] }
                                    : row,
                              ),
                            });
                          }}
                        >
                          {book.sections.map((row, i) => (
                            <option key={i} value={i}>
                              {row.title || `第 ${i + 1} 组`}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </article>
                ))}
              </section>
            ))}
            <button
              className="button secondary"
              disabled={book.sections.length >= 30}
              onClick={() => {
                change({
                  ...book,
                  sections: [
                    ...book.sections,
                    { title: `第 ${book.sections.length + 1} 组`, items: [] },
                  ],
                });
                setActiveGroup(book.sections.length);
              }}
            >
              <Plus size={16} />
              添加章节分组
            </button>
          </fieldset>
          <div className="workbook-footer">
            <span>{busy ? "正在处理…" : `${count} 道题 · A4 排版`}</span>
            <button
              className="button secondary"
              disabled={busy || !count}
              onClick={() => void saveOrExport(false)}
            >
              <Save size={16} />
              保存做题本
            </button>
            <button
              className="button primary"
              disabled={busy || !count}
              onClick={() => void saveOrExport(true)}
            >
              <Download size={16} />
              保存并导出 PDF
            </button>
          </div>
        </section>
      </div>
      {editing && (
        <Modal
          title="编辑做题本题目"
          description="仅修改本册副本。支持 Markdown 和 LaTeX，已有识别提示会保留。"
          onClose={() => setEditing(null)}
          wide
        >
          <form
            onSubmit={(event) => {
              event.preventDefault();
              change({
                ...book,
                sections: book.sections.map((group, i) =>
                  i === editing.group
                    ? {
                        ...group,
                        items: group.items.map((item, j) =>
                          j === editing.index ? editing.item : item,
                        ),
                      }
                    : group,
                ),
              });
              setEditing(null);
            }}
          >
            <label>
              题目名称
              <input
                value={editing.item.title}
                required
                maxLength={200}
                onChange={(event) =>
                  setEditing({ ...editing, item: { ...editing.item, title: event.target.value } })
                }
              />
            </label>
            <MarkdownEditor
              value={editing.item.question}
              onChange={(value) =>
                setEditing({ ...editing, item: { ...editing.item, question: value } })
              }
            />
            <label>
              参考答案（可留空）
              <textarea
                aria-label="参考答案"
                rows={3}
                maxLength={10000}
                value={editing.item.answer}
                onChange={(event) =>
                  setEditing({ ...editing, item: { ...editing.item, answer: event.target.value } })
                }
              />
            </label>
            <label>
              解题步骤（可留空）
              <textarea
                aria-label="解题步骤"
                rows={5}
                maxLength={20000}
                value={editing.item.solution}
                onChange={(event) =>
                  setEditing({
                    ...editing,
                    item: { ...editing.item, solution: event.target.value },
                  })
                }
              />
            </label>
            <div className="modal-actions">
              <button type="button" className="button secondary" onClick={() => setEditing(null)}>
                取消
              </button>
              <button className="button primary">应用到本册</button>
            </div>
          </form>
        </Modal>
      )}
      {cropItem && (
        <ExerciseCropEditor
          courseId={id}
          item={cropItem}
          pageCount={
            documents.find((document) => document.id === cropItem.document_id)?.page_count ||
            cropItem.page_number
          }
          onClose={() => setCropItem(null)}
          onSaved={() => void refreshCrop(cropItem)}
        />
      )}
      {pendingDraft && (
        <Modal
          title="打开自动整理的做题本？"
          description="当前有未保存的修改。打开新草稿会替换当前编辑内容，已保存的做题本仍保留。"
          onClose={() => setPendingDraft(null)}
        >
          <div className="modal-actions">
            <button className="button secondary" onClick={() => setPendingDraft(null)}>
              保留当前编辑
            </button>
            <button className="button primary" onClick={() => applyDraft(pendingDraft)}>
              放弃修改并打开新草稿
            </button>
          </div>
        </Modal>
      )}
      {switchTarget !== null && (
        <Modal
          title="放弃未保存的修改？"
          description="切换做题本会丢弃当前未保存的修改。你也可以先取消并保存。"
          onClose={() => setSwitchTarget(null)}
        >
          <div className="modal-actions">
            <button className="button secondary" onClick={() => setSwitchTarget(null)}>
              继续编辑
            </button>
            <button className="button danger" onClick={() => void openBook(switchTarget)}>
              放弃并切换
            </button>
          </div>
        </Modal>
      )}
      {deleteOpen && (
        <Modal
          title="删除这本做题本？"
          description="只删除本册及其中的编辑，课程知识与课件原题会保留。"
          busy={busy}
          onClose={() => setDeleteOpen(false)}
        >
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setDeleteOpen(false)}
            >
              取消
            </button>
            <button className="button danger" disabled={busy} onClick={() => void deleteBook()}>
              确认删除做题本
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
