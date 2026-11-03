"use client";

import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/http";
import { Notice } from "@/components/ui";
import type { WorkbookScope } from "./workbook-sources";
import type { Workbook } from "../types";

export const typeLabels: Record<string, string> = {
  choice: "选择题",
  fill: "填空题",
  calculation: "计算题",
  proof: "证明题",
  short_answer: "简答题",
  other: "其它题",
};
export const difficultyLabels: Record<string, string> = {
  basic: "基础",
  intermediate: "中等",
  advanced: "提高",
  unknown: "未标注",
};
type Result = Pick<Workbook, "title" | "sections" | "settings"> & {
  report: {
    requested: number;
    selected: number;
    shortfall: number;
    warnings: string[];
    knowledge_tags: string[];
    method: string;
    type_counts: Record<string, number>;
    difficulty_counts: Record<string, number>;
    selection_mode: "all" | "count";
    candidate_count: number;
    duplicates_removed: number;
  };
};

export function AutomaticAssembly({
  courseId,
  scope,
  sourceRevision,
  onApply,
  disabled,
}: {
  courseId: string;
  scope: WorkbookScope;
  sourceRevision: string;
  onApply: (result: Result) => void;
  disabled: boolean;
}) {
  const [instructions, setInstructions] = useState("");
  const [selectionMode, setSelectionMode] = useState<"auto" | "all">("auto");
  const [count, setCount] = useState("");
  const [types, setTypes] = useState<Record<string, string>>({});
  const [levels, setLevels] = useState<Record<string, string>>({});
  const [requireCrops, setRequireCrops] = useState(false);
  const scopeKey = JSON.stringify([scope, sourceRevision]);
  const [preview, setPreview] = useState<{ scope: string; result: Result } | null>(null);
  const result = preview?.scope === scopeKey ? preview.result : null;
  const request = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setBusy(false);
    setError("");
    return () => request.current?.abort();
  }, [scopeKey]);
  async function assemble() {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const next = await api<Result>(`/courses/${courseId}/workbooks/assemble`, {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({
          instructions,
          selection_mode: selectionMode,
          document_ids: scope.document_ids,
          chapter_ids: scope.chapter_ids,
          page_from: scope.page_from ? Number(scope.page_from) : null,
          page_to: scope.page_to ? Number(scope.page_to) : null,
          count: selectionMode === "all" ? null : count ? Number(count) : null,
          type_counts: Object.entries(types)
            .filter(([, value]) => selectionMode !== "all" && Number(value) > 0)
            .map(([question_type, value]) => ({ question_type, count: Number(value) })),
          difficulty_counts: Object.entries(levels)
            .filter(([, value]) => selectionMode !== "all" && Number(value) > 0)
            .map(([difficulty, value]) => ({ difficulty, count: Number(value) })),
          require_crops: requireCrops,
        }),
      });
      if (!controller.signal.aborted) setPreview({ scope: scopeKey, result: next });
    } catch (err) {
      if (!controller.signal.aborted) setError(errorMessage(err));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <details className="workbook-tool-panel">
      <summary>按要求自动整理做题本</summary>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void assemble();
        }}
      >
        <fieldset disabled={busy || disabled}>
          <label className="assembly-total">
            选题方式
            <select
              aria-label="选题方式"
              value={selectionMode}
              onChange={(event) => {
                setSelectionMode(event.target.value as "auto" | "all");
                setPreview(null);
                setError("");
              }}
            >
              <option value="auto">按要求或数量选题</option>
              <option value="all">全部原题并去重</option>
            </select>
          </label>
          {selectionMode === "all" && (
            <p className="workbook-note">
              收集上方所选课件及范围内的全部原题。文字相同的题目只保留一份，图题保守保留。每本最多
              100 题，超过时请按章节分册。
            </p>
          )}
          <label>
            整理要求
            <textarea
              aria-label="整理要求"
              value={instructions}
              maxLength={2000}
              rows={3}
              placeholder={
                selectionMode === "all"
                  ? "可留空，直接整理全部原题。也可补充考查主题。"
                  : "例如：第二章选 10 道题；或：所有题都要，把重复题去掉。"
              }
              onChange={(event) => setInstructions(event.target.value)}
            />
          </label>
          <p className="workbook-note">
            从上方所选范围的已有原题中选题。想全部收集时选择“全部原题并去重”；也可填写考查要求或数量。
          </p>
          <fieldset disabled={selectionMode === "all"} hidden={selectionMode === "all"}>
            <label className="assembly-total">
              总题数
              <input
                type="number"
                min={1}
                max={100}
                value={count}
                placeholder="按要求，默认 10"
                onChange={(event) => setCount(event.target.value)}
              />
            </label>
            <details className="assembly-quotas">
              <summary>题型与难度配额（可选）</summary>
              <p className="workbook-note">
                填写时，各类数量之和需等于总题数。难度来自识别估计或手动标注，未标注的题目不会冒充指定难度。
              </p>
              <div>
                {Object.entries(typeLabels).map(([key, label]) => (
                  <label key={key}>
                    {label}
                    <input
                      aria-label={`${label}数量`}
                      type="number"
                      min={0}
                      max={100}
                      value={types[key] || ""}
                      onChange={(event) => setTypes({ ...types, [key]: event.target.value })}
                    />
                  </label>
                ))}
              </div>
              <div>
                {Object.entries(difficultyLabels).map(([key, label]) => (
                  <label key={key}>
                    {label}
                    <input
                      aria-label={`${label}难度数量`}
                      type="number"
                      min={0}
                      max={100}
                      value={levels[key] || ""}
                      onChange={(event) => setLevels({ ...levels, [key]: event.target.value })}
                    />
                  </label>
                ))}
              </div>
            </details>
          </fieldset>
          <label className="workbook-check">
            <input
              type="checkbox"
              checked={requireCrops}
              onChange={(event) => setRequireCrops(event.target.checked)}
            />
            只选择已确认原题裁片的题目，用于保真打印
          </label>
          <button className="button secondary" disabled={busy}>
            {busy ? "正在整理原题…" : "自动选题并预览"}
          </button>
        </fieldset>
      </form>
      {error && <Notice message={error} />}
      {result && (
        <div className="assembly-result">
          <strong>
            {result.report.selection_mode === "all"
              ? `已整理全部原题，共 ${result.report.selected} 题`
              : `需要 ${result.report.requested} 题，已选 ${result.report.selected} 题`}
            {result.report.shortfall ? `，还缺 ${result.report.shortfall} 题` : ""}
          </strong>
          <p>
            范围内 {result.report.candidate_count} 道候选题，合并 {result.report.duplicates_removed}{" "}
            道文字重复题。
            {result.report.selection_mode === "all" && result.report.method === "rules"
              ? "已在本地完成整理，无需调用模型。"
              : ""}
          </p>
          <p>
            {result.sections.map((group) => `${group.title}：${group.items.length} 题`).join("；")}
          </p>
          <p>
            {Object.entries(result.report.type_counts)
              .map(([key, value]) => `${typeLabels[key] || key} ${value}`)
              .join(" · ")}
          </p>
          {result.report.knowledge_tags.length > 0 && (
            <p>考查知识：{result.report.knowledge_tags.join("、")}</p>
          )}
          {result.report.warnings.map((warning, i) => (
            <p className="workbook-warnings" key={i}>
              {warning}
            </p>
          ))}
          <button
            className="button primary"
            disabled={busy || disabled || !result.report.selected}
            onClick={() => onApply(result)}
          >
            作为新做题本打开
          </button>
        </div>
      )}
    </details>
  );
}
