"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  History,
  GitBranch,
  ImagePlus,
  LoaderCircle,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { Markdown } from "@/components/markdown";
import { Modal, Notice, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/http";
import { useStoredBoolean } from "@/lib/use-stored-boolean";
import type { Course } from "@/features/courses/types";
import type { ChatMessage, Citation, Conversation, IndexStatus } from "../types";
import { BranchCreate } from "./branch-create";
import { DraftImages, MessageImages, useChatImages, type DraftImage } from "./chat-images";

export default function CourseChat({
  branch,
  onClose,
}: { branch?: Conversation; onClose?: () => void } = {}) {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const branchId = branch ? null : search.get("branch");
  const base = `/courses/${id}`;
  const [course, setCourse] = useState<Course | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null | undefined>(branch?.id);
  const [branches, setBranches] = useState<Conversation[]>([]);
  const [openedBranch, setOpenedBranch] = useState<Conversation | null>(null);
  const [fork, setFork] = useState<{ message: ChatMessage; anchor: string } | null>(null);
  const [selection, setSelection] = useState<{
    message: ChatMessage;
    anchor: string;
    x: number;
    y: number;
  } | null>(null);
  const autoStarted = useRef<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [index, setIndex] = useState<IndexStatus | null>(null);
  const [draft, setDraft] = useState("");
  const attachments = useChatImages();
  const fileInput = useRef<HTMLInputElement>(null);
  const draftRequest = useRef<{ signature: string; id: string } | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useStoredBoolean(
    "learnflow.chat.history-collapsed",
  );
  const [loading, setLoading] = useState(true);
  const [reading, setReading] = useState(false);
  const [sending, setSending] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<Conversation | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [pending, setPending] = useState<{
    requestId: string;
    content: string;
    conversationId: string | null;
    images: DraftImage[];
  } | null>(null);
  const active = useRef<string | null | undefined>(undefined);
  const bottom = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!composer.current) return;
    composer.current.style.height = "auto";
    composer.current.style.height = `${Math.min(composer.current.scrollHeight, 112)}px`;
  }, [draft, loading]);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const [nextCourse, threads, state] = await Promise.all([
          api<Course>(base, { signal }),
          branch
            ? Promise.resolve([branch])
            : api<Conversation[]>(`${base}/conversations`, { signal }),
          api<IndexStatus>(`${base}/retrieval/status`, { signal }),
        ]);
        if (signal?.aborted) return;
        setCourse(nextCourse);
        setConversations(threads);
        setIndex(state);
        setSelectedId((old) => (old === undefined ? threads[0]?.id || null : old));
      } catch (err) {
        if (!signal?.aborted) setError(errorMessage(err));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [base, branch],
  );
  const loadMessages = useCallback(
    async (conversationId: string, signal?: AbortSignal) => {
      const rows = await api<ChatMessage[]>(`${base}/conversations/${conversationId}/messages`, {
        signal,
      });
      if (signal?.aborted || active.current !== conversationId) return;
      setMessages((old) =>
        Array.from(
          new Map([...old, ...rows].map((message) => [message.id, message])).values(),
        ).sort((a, b) => a.sequence - b.sequence),
      );
      return rows;
    },
    [base],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useEffect(() => {
    active.current = selectedId;
    setSelection(null);
    setMessages([]);
    setReading(false);
    if (!selectedId) return;
    const controller = new AbortController();
    setReading(true);
    loadMessages(selectedId, controller.signal)
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setReading(false);
      });
    return () => controller.abort();
  }, [selectedId, loadMessages]);
  const loadBranches = useCallback(
    async (conversationId: string, signal?: AbortSignal) => {
      const rows = await api<Conversation[]>(`${base}/conversations/${conversationId}/branches`, {
        signal,
      });
      if (!signal?.aborted && active.current === conversationId) setBranches(rows);
    },
    [base],
  );
  useEffect(() => {
    setBranches([]);
    if (branch || !selectedId) return;
    const controller = new AbortController();
    void loadBranches(selectedId, controller.signal).catch((err) => {
      if (!controller.signal.aborted) setError(errorMessage(err));
    });
    return () => controller.abort();
  }, [branch, selectedId, loadBranches]);
  useEffect(() => {
    if (!branchId) {
      setOpenedBranch(null);
      return;
    }
    const controller = new AbortController();
    api<Conversation>(`${base}/conversations/${encodeURIComponent(branchId)}`, {
      signal: controller.signal,
    })
      .then((row) => {
        if (controller.signal.aborted) return;
        if (!row.parent_conversation_id) throw new Error("这条对话不是分支");
        setSelectedId(row.parent_conversation_id);
        setOpenedBranch(row);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      });
    return () => controller.abort();
  }, [base, branchId]);
  function openBranch(row: Conversation) {
    setOpenedBranch(row);
    const params = new URLSearchParams(search.toString());
    params.set("branch", row.id);
    router.replace(`?${params}`, { scroll: false });
  }
  function closeBranch() {
    setOpenedBranch(null);
    const params = new URLSearchParams(search.toString());
    params.delete("branch");
    router.replace(`/courses/${id}/chat${params.size ? `?${params}` : ""}`, { scroll: false });
    if (selectedId) void loadBranches(selectedId).catch((err) => setError(errorMessage(err)));
  }
  function captureSelection(element: HTMLElement, message: ChatMessage) {
    if (branch) return;
    const selected = window.getSelection();
    const anchor = selected?.toString().trim() || "";
    if (
      !selected?.rangeCount ||
      !anchor ||
      anchor.length > 6000 ||
      !element.contains(selected.anchorNode) ||
      !element.contains(selected.focusNode)
    ) {
      setSelection(null);
      return;
    }
    const rect = selected.getRangeAt(0).getBoundingClientRect();
    setSelection({
      message,
      anchor,
      x: Math.max(8, Math.min(rect.left, innerWidth - 220)),
      y: Math.max(8, Math.min(rect.bottom + 8, innerHeight - 46)),
    });
  }
  const generating = messages.some((message) => message.status === "generating");
  const awaiting = messages.some((message) => message.status === "pending");
  useEffect(() => {
    if (!selection) return;
    const clear = () => {
      if (window.getSelection()?.toString().trim() !== selection.anchor) setSelection(null);
    };
    document.addEventListener("selectionchange", clear);
    window.addEventListener("resize", clear);
    return () => {
      document.removeEventListener("selectionchange", clear);
      window.removeEventListener("resize", clear);
    };
  }, [selection]);
  useEffect(() => {
    if (!selectedId || (!generating && !sending)) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      void loadMessages(selectedId, controller.signal).catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      });
    }, 2000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [selectedId, generating, sending, loadMessages]);
  useEffect(() => {
    if (!index || (index.ready === index.total && !index.rebuild)) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      api<IndexStatus>(`${base}/retrieval/status`, { signal: controller.signal })
        .then((state) => {
          if (!controller.signal.aborted) setIndex(state);
        })
        .catch(() => {});
    }, 5000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [base, index?.ready, index?.total, !!index?.rebuild]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages.length, messages[messages.length - 1]?.status, pending?.requestId]);
  async function send(content: string, requestId?: string, images: DraftImage[] = []) {
    if (sending || generating || (!content.trim() && !images.length && !requestId)) return;
    if (images.length && index?.llm_vision === false) {
      setError("当前模型未启用图片识别，请先到账号设置更换或启用视觉模型。");
      return;
    }
    const signature = content + images.map((image) => image.id).join(",");
    const attempt =
      requestId ||
      (draftRequest.current?.signature === signature
        ? draftRequest.current.id
        : crypto.randomUUID());
    if (!requestId) draftRequest.current = { signature, id: attempt };
    setSending(true);
    setError("");
    let conversationId = selectedId || null;
    setPending({ requestId: attempt, content, conversationId, images });
    let saved = false;
    try {
      if (!conversationId) {
        const conversation = await api<Conversation>(`${base}/conversations`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        conversationId = conversation.id;
        active.current = conversationId;
        setSelectedId(conversationId);
        setPending({ requestId: attempt, content, conversationId, images });
      }
      const body = images.length
        ? new FormData()
        : JSON.stringify({ content, request_id: attempt });
      if (body instanceof FormData) {
        body.set("content", content);
        body.set("request_id", attempt);
        images.forEach((image) => body.append("files", image.file));
      }
      await api<ChatMessage>(
        `${base}/conversations/${conversationId}/messages${images.length ? "/with-images" : ""}`,
        { method: "POST", body },
      );
      saved = true;
      await loadMessages(conversationId);
    } catch (err) {
      setError(errorMessage(err));
      if (conversationId) {
        const rows = await loadMessages(conversationId).catch(() => undefined);
        saved = !!rows?.some(
          (message) => message.request_id === attempt && message.role === "user",
        );
      }
    } finally {
      if (saved && !requestId) {
        setDraft("");
        attachments.clear();
        setError("");
        draftRequest.current = null;
      }
      await load();
      setSending(false);
      setPending(null);
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void send(draft.trim(), undefined, attachments.images);
  }
  useEffect(() => {
    if (!branch || reading || sending || generating) return;
    const waiting = messages.find(
      (message) => message.status === "pending" && message.role === "assistant",
    );
    const question = messages.find(
      (message) => message.role === "user" && message.request_id === waiting?.request_id,
    );
    if (!waiting || !question || autoStarted.current === waiting.id) return;
    autoStarted.current = waiting.id;
    void send(question.content, waiting.request_id);
  }, [branch, messages, reading, sending, generating]);
  async function deleteConversation() {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await api(`${base}/conversations/${deleting.id}`, { method: "DELETE" });
      if (selectedId === deleting.id) {
        active.current = null;
        setSelectedId(null);
        setMessages([]);
      }
      setDeleting(null);
      await load();
      if (!branch && selectedId && selectedId !== deleting.id) await loadBranches(selectedId);
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  }
  async function updateIndex() {
    setIndexing(true);
    setError("");
    try {
      await api(`${base}/retrieval/index`, { method: "POST" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIndexing(false);
    }
  }
  async function older() {
    if (!selectedId || !messages.length) return;
    const conversationId = selectedId;
    try {
      const rows = await api<ChatMessage[]>(
        `${base}/conversations/${conversationId}/messages?before=${messages[0].sequence}`,
      );
      if (active.current !== conversationId) return;
      setMessages((old) =>
        Array.from(
          new Map([...rows, ...old].map((message) => [message.id, message])).values(),
        ).sort((a, b) => a.sequence - b.sequence),
      );
    } catch (err) {
      if (active.current === conversationId) setError(errorMessage(err));
    }
  }
  if (loading) return <Spinner label="正在读取课程问答" />;
  if (!course) return <Notice message={error || "课程不存在"} retry={() => void load()} />;
  const optimistic =
    pending &&
    pending.conversationId === (selectedId || null) &&
    !messages.some((message) => message.request_id === pending.requestId);
  return (
    <>
      {branch ? (
        <header className="branch-heading">
          <div>
            <h2 id="branch-title">
              <GitBranch size={18} />
              分支提问
            </h2>
            <p>{course.name}</p>
          </div>
          <button className="button secondary" onClick={onClose}>
            <ArrowLeft size={15} />
            返回主对话
          </button>
        </header>
      ) : (
        <>
          <header className="chat-page-heading">
            <div className="chat-heading-title">
              <Link
                className="chat-back-link"
                href={`/courses/${id}`}
                aria-label="返回课程课件"
                title="返回课程课件"
              >
                <ArrowLeft size={18} />
              </Link>
              <div>
                <h1>课程问答</h1>
                <p>{course.name}</p>
              </div>
            </div>
            <div className="chat-heading-actions">
              <button
                type="button"
                className="button secondary chat-desktop-history-toggle"
                aria-label={historyCollapsed ? "展开对话历史" : "收起对话历史"}
                title={historyCollapsed ? "展开对话历史" : "收起对话历史"}
                aria-expanded={!historyCollapsed}
                aria-controls="course-chat-history"
                onClick={() => setHistoryCollapsed(!historyCollapsed)}
              >
                {historyCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
                {historyCollapsed ? "对话历史" : "收起历史"}
              </button>
              <button
                type="button"
                className="button secondary chat-history-toggle"
                aria-label="历史对话"
                title="历史对话"
                aria-expanded={historyOpen}
                aria-controls="course-chat-history"
                onClick={() => setHistoryOpen(!historyOpen)}
              >
                <History size={16} />
                <span>历史对话</span>
              </button>
              <Link className="button secondary" href={`/courses/${id}/knowledge`}>
                <BookOpen size={15} />
                课程知识库
              </Link>
            </div>
          </header>
        </>
      )}
      {branch && (
        <details className="branch-context">
          <summary>
            提问背景 ·{" "}
            {branch.context_mode === "minimal"
              ? "仅片段和原问题"
              : branch.context_mode === "full"
                ? "包含更多前文"
                : "围绕当前回答"}
          </summary>
          <p className="muted">原问题：{branch.source_question}</p>
          {!!branch.source_images?.length && <MessageImages images={branch.source_images} />}
          <div className="branch-anchor-preview">
            <Markdown>{branch.anchor_text}</Markdown>
          </div>
          {branch.context_truncated && <p className="muted">继承的上下文较长，已截取部分内容。</p>}
        </details>
      )}
      {error && <Notice message={error} />}
      <div
        className={`chat-layout${branch ? " is-branch" : ""}${historyOpen ? " is-history-open" : ""}${historyCollapsed ? " is-history-collapsed" : ""}`}
      >
        {historyOpen && (
          <button
            className="chat-history-scrim"
            aria-label="收起对话历史"
            onClick={() => setHistoryOpen(false)}
          />
        )}
        {!branch && (
          <aside id="course-chat-history" className="chat-conversations" aria-label="问答历史">
            <button
              type="button"
              className="icon-button chat-history-close"
              aria-label="关闭对话历史"
              onClick={() => setHistoryOpen(false)}
            >
              <X size={17} />
            </button>
            <button
              className="button secondary"
              disabled={sending}
              onClick={() => {
                active.current = null;
                setSelectedId(null);
                setMessages([]);
                setDraft("");
                attachments.clear();
                setError("");
                setHistoryOpen(false);
              }}
            >
              <Plus size={15} />
              新对话
            </button>
            <div className="chat-conversation-list">
              {conversations.length ? (
                conversations.map((conversation) => (
                  <div
                    key={conversation.id}
                    className={`chat-conversation ${selectedId === conversation.id ? "selected" : ""}`}
                  >
                    <button
                      disabled={sending}
                      onClick={() => {
                        active.current = conversation.id;
                        setSelectedId(conversation.id);
                        setDraft("");
                        attachments.clear();
                        setHistoryOpen(false);
                      }}
                    >
                      {conversation.title}
                    </button>
                    <button
                      className="icon-button"
                      disabled={sending}
                      aria-label={`删除对话 ${conversation.title}`}
                      onClick={() => {
                        setDeleting(conversation);
                        setDeleteError("");
                      }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))
              ) : (
                <p>这里会保存这门课的问答记录。</p>
              )}
            </div>
            {index && (
              <div className="chat-index-state">
                {index.rebuild && (
                  <span>
                    账号正在更新 Embedding：{index.rebuild.ready} / {index.rebuild.total}
                  </span>
                )}
                <span>
                  {index.total
                    ? `知识索引 ${index.ready} / ${index.total}`
                    : "知识库暂无内容，可先上传课件。"}
                </span>
                <Link href="/settings">账号模型设置</Link>
                {index.ready < index.total && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={indexing}
                    onClick={() => void updateIndex()}
                  >
                    {indexing ? "正在提交…" : "更新知识索引"}
                  </button>
                )}
              </div>
            )}
          </aside>
        )}
        <section className="chat-main" aria-label={branch ? "分支对话" : "课程对话"}>
          <div
            className="chat-messages"
            aria-label={branch ? "分支消息" : "对话消息"}
            onScroll={() => setSelection(null)}
          >
            {reading && !messages.length ? (
              <Spinner label="正在读取对话" />
            ) : !messages.length && !optimistic ? (
              <div className="chat-empty">
                <MessageSquare size={30} strokeWidth={1.4} />
                <h2>暂无消息</h2>
                <p>可以询问定义、公式的适用条件，或课件中某道例题的解题思路。</p>
              </div>
            ) : null}
            {messages[0]?.sequence > 1 && (
              <button className="text-button chat-load-older" onClick={() => void older()}>
                查看更早的消息
              </button>
            )}
            {messages.map((message) => (
              <article key={message.id} className={`chat-message ${message.role}`}>
                <div className="chat-message-label">
                  {message.role === "user" ? "你" : "课程助手"}
                </div>
                {!!message.images?.length && <MessageImages images={message.images} />}
                {message.status === "generating" || (message.status === "pending" && sending) ? (
                  <p className="chat-generating">
                    <LoaderCircle size={15} className="spin" />
                    {stageLabel(message.workflow_stage)}
                  </p>
                ) : message.status === "failed" || message.status === "pending" ? (
                  <div className="chat-failed">
                    <p>{message.error || "问题已保存，可以继续生成回答。"}</p>
                    <button
                      className="button secondary"
                      disabled={sending || generating}
                      onClick={() => {
                        const question = messages.find(
                          (item) => item.role === "user" && item.request_id === message.request_id,
                        );
                        if (question) void send(question.content, message.request_id);
                      }}
                    >
                      {message.status === "pending" ? "生成回答" : "重试回答"}
                    </button>
                  </div>
                ) : (
                  <>
                    <div
                      className="chat-answer-content"
                      onPointerUp={(event) =>
                        message.role === "assistant" &&
                        captureSelection(event.currentTarget, message)
                      }
                      onKeyUp={(event) =>
                        message.role === "assistant" &&
                        captureSelection(event.currentTarget, message)
                      }
                    >
                      <Markdown>
                        {message.role === "assistant" ? linkedAnswer(message) : message.content}
                      </Markdown>
                      {message.supplement && (
                        <div className="chat-supplement">
                          <h3>补充解释</h3>
                          <Markdown>{message.supplement}</Markdown>
                        </div>
                      )}
                    </div>
                    {message.citations.length > 0 && (
                      <div className="chat-citations">
                        {message.citations.map((citation) => (
                          <CitationCard
                            key={citation.key}
                            citation={citation}
                            courseId={id}
                            messageId={message.id}
                          />
                        ))}
                      </div>
                    )}
                    {message.warnings.length > 0 && (
                      <div className="chat-warnings">
                        {message.warnings.map((warning, index) => (
                          <p key={index}>{warning}</p>
                        ))}
                      </div>
                    )}
                    {message.role === "assistant" &&
                      ["conversation", "clarification", "context", "image"].includes(
                        message.retrieval_mode || "",
                      ) && (
                        <p className="chat-answer-basis">
                          {message.retrieval_mode === "image"
                            ? "根据图片分析"
                            : message.retrieval_mode === "context"
                              ? "沿用对话中的课程依据"
                              : message.retrieval_mode === "clarification"
                                ? "需要补充问题信息"
                                : "根据对话上下文"}
                        </p>
                      )}
                    {!branch && message.role === "assistant" && (
                      <div className="chat-message-branches">
                        <button
                          className="text-button"
                          onClick={() => {
                            setSelection(null);
                            setFork({ message, anchor: "" });
                          }}
                        >
                          <GitBranch size={14} />
                          分支提问
                        </button>
                        {branches
                          .filter((row) => row.parent_message_id === message.id)
                          .map((row) => (
                            <div className="saved-branch" key={row.id}>
                              <button className="text-button" onClick={() => openBranch(row)}>
                                <GitBranch size={13} />
                                {row.title}
                              </button>
                              <button
                                className="icon-button"
                                aria-label={`删除分支 ${row.title}`}
                                onClick={() => {
                                  setDeleting(row);
                                  setDeleteError("");
                                }}
                              >
                                <Trash2 size={13} />
                              </button>
                            </div>
                          ))}
                      </div>
                    )}
                  </>
                )}
              </article>
            ))}
            {optimistic && (
              <article className="chat-message user">
                <div className="chat-message-label">你</div>
                <p>{pending.content}</p>
                {!!pending.images.length && (
                  <div className="chat-message-images">
                    {pending.images.map((image) => (
                      <img key={image.id} src={image.url} alt={image.file.name} />
                    ))}
                  </div>
                )}
              </article>
            )}
            {sending && !generating && (
              <p className="chat-generating">
                <LoaderCircle size={15} className="spin" />
                正在处理问题…
              </p>
            )}
            <div ref={bottom} />
          </div>
          <form
            className="chat-composer"
            onSubmit={submit}
            onDragOver={(event) => {
              if (event.dataTransfer.types.includes("Files")) event.preventDefault();
            }}
            onDrop={(event) => {
              if (event.dataTransfer.files.length) {
                event.preventDefault();
                if (!sending && !generating && !awaiting)
                  attachments.add(Array.from(event.dataTransfer.files));
              }
            }}
          >
            {attachments.images.length > 0 && (
              <DraftImages
                images={attachments.images}
                remove={attachments.remove}
                disabled={sending || generating}
              />
            )}
            {attachments.error && (
              <p className="chat-upload-error" role="alert">
                {attachments.error}
              </p>
            )}
            {attachments.images.length > 0 && index?.llm_vision === false && (
              <p className="chat-upload-error">
                当前模型未启用图片识别。<Link href="/settings">前往账号设置</Link>
              </p>
            )}
            <input
              ref={fileInput}
              className="visually-hidden"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              aria-label={branch ? "添加分支图片" : "添加图片"}
              disabled={sending || generating || awaiting}
              onChange={(event) => {
                attachments.add(Array.from(event.target.files || []));
                event.target.value = "";
              }}
            />
            <label
              htmlFor={branch ? `branch-question-${branch.id}` : "course-question"}
              className="visually-hidden"
            >
              {branch ? "在分支中继续提问" : "向课程助手提问"}
            </label>
            <textarea
              id={branch ? `branch-question-${branch.id}` : "course-question"}
              ref={composer}
              rows={1}
              maxLength={2000}
              value={draft}
              disabled={sending || generating || awaiting}
              placeholder="输入问题，Shift + Enter 换行"
              onChange={(event) => setDraft(event.target.value)}
              onPaste={(event) => {
                const files = Array.from(event.clipboardData.items)
                  .filter((item) => item.kind === "file")
                  .map((item) => item.getAsFile())
                  .filter((file): file is File => !!file);
                if (files.length) {
                  event.preventDefault();
                  attachments.add(files);
                }
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  if (draft.trim() || attachments.images.length)
                    void send(draft.trim(), undefined, attachments.images);
                }
              }}
            />
            <div className="chat-composer-actions">
              <button
                type="button"
                className="icon-button chat-attach-button"
                aria-label={branch ? "选择分支图片" : "选择图片"}
                title="添加图片（每张不超过 5 MB，最多 4 张）"
                disabled={sending || generating || awaiting || attachments.images.length >= 4}
                onClick={() => fileInput.current?.click()}
              >
                <ImagePlus size={19} />
              </button>
              <button
                className="button primary"
                disabled={
                  sending ||
                  generating ||
                  awaiting ||
                  (!draft.trim() && !attachments.images.length) ||
                  (attachments.images.length > 0 && index?.llm_vision === false)
                }
              >
                <Send size={14} />
                发送
              </button>
            </div>
            <p className="chat-composer-hint">
              Enter 发送 · Shift + Enter 换行 · 可粘贴图片 · 回答可展开引用核对来源
            </p>
          </form>
        </section>
      </div>
      {selection && !fork && (
        <button
          className="button primary branch-selection-action"
          style={{ left: selection.x, top: selection.y }}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            setFork(selection);
            setSelection(null);
            window.getSelection()?.removeAllRanges();
          }}
        >
          <GitBranch size={14} />
          针对选中内容提问
        </button>
      )}
      {fork && (
        <BranchCreate
          base={base}
          message={fork.message}
          anchor={fork.anchor}
          onClose={() => setFork(null)}
          onCreated={(row) => {
            setFork(null);
            setBranches((old) => [row, ...old.filter((item) => item.id !== row.id)]);
            openBranch(row);
          }}
        />
      )}
      {!branch && openedBranch && <BranchDrawer branch={openedBranch} onClose={closeBranch} />}
      {deleting && (
        <Modal
          title="删除这段对话？"
          description={
            deleting.parent_conversation_id
              ? "这个分支及其消息、引用记录会一并删除。"
              : "这段主对话、关联分支及引用记录会一并删除，课程知识会保留。"
          }
          busy={deleteBusy}
          onClose={() => setDeleting(null)}
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
              onClick={() => void deleteConversation()}
            >
              {deleteBusy ? "正在删除…" : "确认删除"}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function stageLabel(stage: string | null) {
  return (
    (
      {
        planning: "正在理解问题…",
        checking_context: "正在核对已有依据…",
        retrieving: "正在检索课程知识…",
        generating: "正在生成回答…",
        validating: "正在核对回答引用…",
        saving: "正在保存回答…",
      } as Record<string, string>
    )[stage || ""] || "正在准备回答…"
  );
}

function BranchDrawer({ branch, onClose }: { branch: Conversation; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="branch-drawer"
      aria-label="分支提问"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <CourseChat key={branch.id} branch={branch} onClose={onClose} />
    </dialog>
  );
}

function linkedAnswer(message: ChatMessage) {
  const available = new Set(message.citations.map((citation) => citation.key));
  return message.content.replace(/\[(K\d+)\]/g, (value, key) =>
    available.has(key) ? `[${key}](#citation-${message.id}-${key})` : value,
  );
}

function CitationCard({
  citation,
  courseId,
  messageId,
}: {
  citation: Citation;
  courseId: string;
  messageId: string;
}) {
  const href = `/courses/${courseId}/knowledge?point=${citation.knowledge_id}${citation.knowledge_status === "archived" ? "&status=archived" : ""}`;
  return (
    <details id={`citation-${messageId}-${citation.key}`} className="chat-citation">
      <summary>
        <span>{citation.key}</span>
        {citation.title} · 第 {citation.version} 版
      </summary>
      {!citation.current && (
        <p className="chat-citation-stale">这条知识已更新或归档，当前回答保留当时引用的版本。</p>
      )}
      <div className="chat-citation-text">
        <Markdown>{citation.text}</Markdown>
      </div>
      {citation.knowledge_status !== "deleted" && <Link href={href}>查看知识点</Link>}
      {citation.sources.map((source, index) => (
        <div key={index}>
          {source.available && source.document_id ? (
            <a
              href={`/api/documents/${source.document_id}/file#page=${source.page_number}`}
              target="_blank"
              rel="noreferrer"
            >
              {source.filename} · 第 {source.page_number} 页
            </a>
          ) : (
            <span>
              {source.filename} · 第 {source.page_number} 页（原文件已删除）
            </span>
          )}
        </div>
      ))}
    </details>
  );
}
