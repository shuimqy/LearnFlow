"use client";

import { FormEvent, useState } from "react";
import { Check, LoaderCircle } from "lucide-react";
import { api, errorMessage } from "@/lib/http";
import type { Course, CourseColor } from "@/features/courses/types";
import { Modal, Notice } from "@/components/ui";

const colors: { value: CourseColor; label: string }[] = [
  { value: "sage", label: "松绿" },
  { value: "sand", label: "麦黄" },
  { value: "blue", label: "雾蓝" },
  { value: "rose", label: "陶红" },
  { value: "lavender", label: "浅紫" },
];

export function CourseForm({
  course,
  onClose,
  onSaved,
}: {
  course?: Course;
  onClose: () => void;
  onSaved: (course: Course) => Promise<void>;
}) {
  const [name, setName] = useState(course?.name || "");
  const [description, setDescription] = useState(course?.description || "");
  const [color, setColor] = useState<CourseColor>(course?.color || "sage");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<Course>(course ? `/courses/${course.id}` : "/courses", {
        method: course ? "PATCH" : "POST",
        body: JSON.stringify({ name: name.trim(), description: description.trim(), color }),
      });
      await onSaved(result);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }
  return (
    <Modal title={course ? "课程设置" : "新建课程"} onClose={onClose} busy={busy}>
      <form onSubmit={submit} className="form-stack">
        <label>
          课程名称
          <input
            autoFocus
            required
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：线性代数"
          />
        </label>
        <label>
          课程简介 <span className="optional">选填</span>
          <textarea
            maxLength={2000}
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="记下这门课的内容或学习目标"
          />
        </label>
        <fieldset className="color-field">
          <legend>课程颜色</legend>
          <div className="color-options">
            {colors.map((item) => (
              <button
                type="button"
                key={item.value}
                aria-label={item.label}
                aria-pressed={color === item.value}
                className={`color-choice tint-${item.value} ${color === item.value ? "selected" : ""}`}
                onClick={() => setColor(item.value)}
              >
                {color === item.value && <Check size={16} />}
              </button>
            ))}
          </div>
        </fieldset>
        {error && <Notice message={error} />}
        <div className="modal-actions">
          <button type="button" className="button secondary" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button className="button primary" disabled={busy || !name.trim()}>
            {busy && <LoaderCircle size={16} className="spin" />}
            {course ? "保存修改" : "创建课程"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
