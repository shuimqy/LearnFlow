"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { Modal, Notice, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/http";
import type { Exercise } from "../types";
import { difficultyLabels, typeLabels } from "./automatic-assembly";

type Region = {
  role: "question" | "figure";
  page_number: number;
  bbox: [number, number, number, number];
};
type Layout = {
  draft_id: string;
  version: number;
  status: string;
  regions: Region[];
  question_type: string;
  difficulty: string;
  knowledge_tags: string[];
  warnings: string[];
};

export function ExerciseCropEditor({
  courseId,
  item,
  pageCount,
  onClose,
  onSaved,
}: {
  courseId: string;
  item: Exercise;
  pageCount: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [layout, setLayout] = useState<Layout | null>(null);
  const [page, setPage] = useState(item.page_number);
  const [active, setActive] = useState(-1);
  const [role, setRole] = useState<Region["role"]>("question");
  const [tags, setTags] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [imageError, setImageError] = useState(false);
  const [drawing, setDrawing] = useState<[number, number, number, number] | null>(null);
  const anchor = useRef<[number, number] | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void api<Layout>(`/courses/${courseId}/exercises/${item.draft_id}/layout`, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) {
          setLayout(result);
          setTags(result.knowledge_tags.join("、"));
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      });
    return () => controller.abort();
  }, [courseId, item.draft_id]);
  function location(event: PointerEvent<HTMLDivElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    ];
  }
  function box(start: [number, number], end: [number, number]): Region["bbox"] {
    return [
      Math.min(start[0], end[0]),
      Math.min(start[1], end[1]),
      Math.max(start[0], end[0]),
      Math.max(start[1], end[1]),
    ];
  }
  function setRegions(regions: Region[]) {
    if (layout) {
      setLayout({ ...layout, regions });
      setConfirmed(false);
    }
  }
  async function save(isConfirmed: boolean) {
    if (!layout) return;
    setBusy(true);
    setError("");
    try {
      await api(`/courses/${courseId}/exercises/${item.draft_id}/layout`, {
        method: "PUT",
        body: JSON.stringify({
          expected_version: layout.version,
          regions: layout.regions,
          question_type: layout.question_type,
          difficulty: layout.difficulty,
          knowledge_tags: tags
            .split(/[、,，\n]/)
            .map((tag) => tag.trim())
            .filter(Boolean),
          confirmed: isConfirmed,
        }),
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={`原题与题图：${item.title}`}
      description="在原页上拖动框选。原题框包含完整题干、选项及题图；题图框仅包含文字重排版需要的图表。请排除答案与解题步骤。跨页题可追加多个页面区域。"
      wide
      busy={busy}
      onClose={onClose}
    >
      {error && <Notice message={error} />}
      {!layout ? (
        !error && <Spinner label="读取原题区域" />
      ) : (
        <fieldset disabled={busy} className="crop-editor">
          <div className="crop-metadata">
            <label>
              题型
              <select
                value={layout.question_type}
                onChange={(event) => setLayout({ ...layout, question_type: event.target.value })}
              >
                {Object.entries(typeLabels).map(([value, name]) => (
                  <option key={value} value={value}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              难度（估计，可修正）
              <select
                value={layout.difficulty}
                onChange={(event) => setLayout({ ...layout, difficulty: event.target.value })}
              >
                {Object.entries(difficultyLabels).map(([value, name]) => (
                  <option key={value} value={value}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              考查知识点（用顿号分隔）
              <input
                value={tags}
                maxLength={900}
                onChange={(event) => setTags(event.target.value)}
              />
            </label>
          </div>
          {layout.warnings.map((warning, i) => (
            <p key={i} className="workbook-warnings">
              {warning}
            </p>
          ))}
          <div className="crop-toolbar">
            <label>
              原页页码
              <input
                aria-label="裁片原页页码"
                type="number"
                min={1}
                max={pageCount}
                value={page}
                onChange={(event) => {
                  setPage(Math.max(1, Math.min(pageCount, Number(event.target.value))));
                  setImageError(false);
                  setActive(-1);
                }}
              />
            </label>
            <label>
              区域用途
              <select
                aria-label="区域用途"
                value={role}
                onChange={(event) => {
                  const value = event.target.value as Region["role"];
                  setRole(value);
                  if (active >= 0)
                    setRegions(
                      layout.regions.map((region, i) =>
                        i === active ? { ...region, role: value } : region,
                      ),
                    );
                }}
              >
                <option value="question">完整原题</option>
                <option value="figure">仅题图 / 表格</option>
              </select>
            </label>
            <button
              className="button secondary"
              disabled={layout.regions.length >= 12}
              onClick={() => {
                setActive(-1);
                setDrawing(null);
              }}
            >
              追加区域
            </button>
          </div>
          <p className="workbook-note">
            {active < 0
              ? "拖动框选以追加区域。"
              : `正在调整区域 ${active + 1}，重新拖动会替换该框。`}
            单击下方区域可调整；也可直接填写 0–1 的坐标。
          </p>
          {imageError ? (
            <Notice message="原页暂时无法读取，请检查课件是否存在。" />
          ) : (
            <div
              className="crop-canvas"
              aria-label="原页框选画布"
              onPointerDown={(event) => {
                if (busy || event.button !== 0) return;
                event.preventDefault();
                anchor.current = location(event);
                setDrawing([...anchor.current, ...anchor.current]);
                event.currentTarget.setPointerCapture(event.pointerId);
              }}
              onPointerMove={(event) => {
                if (anchor.current) setDrawing(box(anchor.current, location(event)));
              }}
              onPointerUp={(event) => {
                if (!anchor.current) return;
                const bbox = box(anchor.current, location(event));
                anchor.current = null;
                setDrawing(null);
                if (bbox[2] - bbox[0] < 0.005 || bbox[3] - bbox[1] < 0.005) return;
                const region = { role, page_number: page, bbox };
                if (active >= 0)
                  setRegions(layout.regions.map((old, i) => (i === active ? region : old)));
                else if (layout.regions.length < 12) {
                  setRegions([...layout.regions, region]);
                  setActive(layout.regions.length);
                }
              }}
              onPointerCancel={() => {
                anchor.current = null;
                setDrawing(null);
              }}
            >
              {/* 使用原生图片保持框选坐标与服务端裁切一致。 */}
              <img
                src={`/api/documents/${item.document_id}/pages/${page}/image`}
                alt={`课件第 ${page} 页`}
                draggable={false}
                onError={() => setImageError(true)}
              />
              {layout.regions.map(
                (region, i) =>
                  region.page_number === page && (
                    <div
                      key={i}
                      className={`crop-box ${region.role} ${active === i ? "active" : ""}`}
                      style={{
                        left: `${region.bbox[0] * 100}%`,
                        top: `${region.bbox[1] * 100}%`,
                        width: `${(region.bbox[2] - region.bbox[0]) * 100}%`,
                        height: `${(region.bbox[3] - region.bbox[1]) * 100}%`,
                      }}
                    >
                      <span>
                        {i + 1} · {region.role === "question" ? "原题" : "题图"}
                      </span>
                    </div>
                  ),
              )}
              {drawing && (
                <div
                  className={`crop-box ${role} active`}
                  style={{
                    left: `${drawing[0] * 100}%`,
                    top: `${drawing[1] * 100}%`,
                    width: `${(drawing[2] - drawing[0]) * 100}%`,
                    height: `${(drawing[3] - drawing[1]) * 100}%`,
                  }}
                />
              )}
            </div>
          )}
          <div className="crop-regions">
            {layout.regions.map((region, i) => (
              <div key={i}>
                <button
                  className={`text-button ${active === i ? "selected" : ""}`}
                  onClick={() => {
                    setActive(i);
                    setPage(region.page_number);
                    setRole(region.role);
                    setImageError(false);
                  }}
                >
                  区域 {i + 1} · 第 {region.page_number} 页 ·{" "}
                  {region.role === "question" ? "原题" : "题图"}
                </button>
                {region.bbox.map((value, coordinate) => (
                  <label key={coordinate}>
                    {["左", "上", "右", "下"][coordinate]}
                    <input
                      aria-label={`区域 ${i + 1} ${["左", "上", "右", "下"][coordinate]}坐标`}
                      type="number"
                      min={0}
                      max={1}
                      step={0.001}
                      value={Number(value.toFixed(4))}
                      onChange={(event) =>
                        setRegions(
                          layout.regions.map((row, index) =>
                            index === i
                              ? {
                                  ...row,
                                  bbox: row.bbox.map((old, k) =>
                                    k === coordinate ? Number(event.target.value) : old,
                                  ) as Region["bbox"],
                                }
                              : row,
                          ),
                        )
                      }
                    />
                  </label>
                ))}
                <button
                  className="text-button danger-text"
                  onClick={() => {
                    setRegions(layout.regions.filter((_, index) => index !== i));
                    setActive(-1);
                  }}
                >
                  移除区域 {i + 1}
                </button>
              </div>
            ))}
          </div>
          <label className="workbook-check">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            已核对完整原题和题图，裁片不包含答案与解题步骤
          </label>
          <div className="modal-actions">
            <button className="button secondary" onClick={() => void save(false)}>
              保存待核对
            </button>
            <button
              className="button primary"
              disabled={!confirmed || !layout.regions.some((region) => region.role === "question")}
              onClick={() => void save(true)}
            >
              {busy ? "正在裁切保存…" : "确认并保存裁片"}
            </button>
          </div>
        </fieldset>
      )}
    </Modal>
  );
}
