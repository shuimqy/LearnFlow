"use client";

import { FormEvent, useRef, useState } from "react";
import { Markdown } from "@/components/markdown";
import { Modal, Notice } from "@/components/ui";
import { api, errorMessage } from "@/lib/http";
import type { ChatMessage, Conversation } from "../types";

export function BranchCreate({
  base,
  message,
  anchor,
  onClose,
  onCreated,
}: {
  base: string;
  message: ChatMessage;
  anchor: string;
  onClose: () => void;
  onCreated: (branch: Conversation) => void;
}) {
  const requestId = useRef(crypto.randomUUID());
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("focused");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !question.trim()) return;
    setBusy(true);
    setError("");
    try {
      const branch = await api<Conversation>(
        `${base}/conversations/${message.conversation_id}/branches`,
        {
          method: "POST",
          body: JSON.stringify({
            request_id: requestId.current,
            parent_message_id: message.id,
            question: question.trim(),
            anchor_text: anchor,
            context_mode: mode,
          }),
        },
      );
      onCreated(branch);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="创建分支提问"
      description="分支单独保存，可以随时返回主对话。"
      onClose={onClose}
      busy={busy}
      wide
    >
      <form onSubmit={submit} className="branch-create-form">
        <div>
          <p className="field-label">{anchor ? "选中片段" : "从这条回答继续"}</p>
          <div className="branch-anchor-preview">
            <Markdown>{anchor || message.content}</Markdown>
          </div>
        </div>
        <label className="field">
          分支问题
          <textarea
            autoFocus
            required
            rows={3}
            maxLength={2000}
            value={question}
            disabled={busy}
            onChange={(event) => {
              setQuestion(event.target.value);
              requestId.current = crypto.randomUUID();
            }}
            placeholder="你想进一步了解什么？"
          />
        </label>
        <label className="field">
          上下文范围
          <select
            value={mode}
            disabled={busy}
            onChange={(event) => {
              setMode(event.target.value);
              requestId.current = crypto.randomUUID();
            }}
          >
            <option value="focused">围绕当前回答（推荐）</option>
            <option value="full">包含更多前文</option>
            <option value="minimal">仅选中片段和原问题</option>
          </select>
        </label>
        <p className="muted branch-context-help">
          {mode === "full"
            ? "继承当前回答及之前最多 20 条消息；过长内容会截取。"
            : mode === "minimal"
              ? "适合只讨论一个定义、公式或步骤。"
              : "继承当前回答及最近少量前文。每次提问仍会重新检索课程知识。"}
        </p>
        {error && <Notice message={error} />}
        <div className="modal-actions">
          <button type="button" className="button secondary" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button className="button primary" disabled={busy || !question.trim()}>
            {busy ? "正在创建…" : "创建并提问"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
