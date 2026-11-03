"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight, BookOpen, FileText, LayoutGrid, List, Plus, Search } from "lucide-react";
import { CourseForm } from "@/features/courses/components/course-form";
import { useCourses } from "@/features/courses/course-provider";
import { Notice, Spinner } from "@/components/ui";
import { formatDate } from "@/lib/format";

export default function CoursesPage() {
  const { courses, loading, error, refresh } = useCourses();
  const [createOpen, setCreateOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("recent");
  const [view, setView] = useState("grid");
  const visible = useMemo(
    () =>
      courses
        .filter((item) =>
          `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase()),
        )
        .sort((a, b) =>
          sort === "name"
            ? a.name.localeCompare(b.name, "zh-CN")
            : b.updated_at.localeCompare(a.updated_at),
        ),
    [courses, query, sort],
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>
            我的课程<span className="heading-dot">.</span>
          </h1>
        </div>
        <button className="button primary" onClick={() => setCreateOpen(true)}>
          <Plus size={17} />
          新建课程
        </button>
      </div>
      <div className="library-toolbar">
        <div className="library-tab">
          全部课程<span>{courses.length}</span>
        </div>
        <div className="toolbar-controls">
          <label className="search-field">
            <Search size={16} />
            <input
              aria-label="搜索课程"
              placeholder="搜索课程…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <select
            className="sort-select"
            aria-label="课程排序"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            <option value="recent">最近更新</option>
            <option value="name">名称排序</option>
          </select>
          <div className="view-toggle">
            <button
              className={view === "grid" ? "selected" : ""}
              aria-label="卡片视图"
              aria-pressed={view === "grid"}
              onClick={() => setView("grid")}
            >
              <LayoutGrid size={16} />
            </button>
            <button
              className={view === "list" ? "selected" : ""}
              aria-label="列表视图"
              aria-pressed={view === "list"}
              onClick={() => setView("list")}
            >
              <List size={17} />
            </button>
          </div>
        </div>
      </div>
      {loading ? (
        <Spinner label="正在读取课程" />
      ) : error ? (
        <Notice message={error} retry={() => void refresh()} />
      ) : courses.length === 0 ? (
        <>
          <section className="library-empty">
            <div className="paper-stack" aria-hidden="true">
              <div className="paper-back" />
              <div className="paper-front">
                <BookOpen size={31} strokeWidth={1.2} />
                <span />
                <span />
                <span />
              </div>
              <span className="paper-pin">01</span>
            </div>
            <div className="empty-copy">
              <h2>暂无课程</h2>
              <button className="button primary" onClick={() => setCreateOpen(true)}>
                <Plus size={16} />
                创建课程
              </button>
            </div>
          </section>
        </>
      ) : (
        <>
          <div className="results-caption">
            {query
              ? `找到 ${visible.length} 门课程`
              : `共 ${courses.length} 门课程 · ${courses.reduce((total, item) => total + item.document_count, 0)} 份课件`}
          </div>
          {visible.length === 0 ? (
            <div className="plain-empty">
              <Search size={25} />
              <h2>没有找到相关课程</h2>
              <p>换个关键词，或清空搜索再看看。</p>
              <button className="button secondary" onClick={() => setQuery("")}>
                清空搜索
              </button>
            </div>
          ) : (
            <div className={`course-grid ${view === "list" ? "course-list" : ""}`}>
              {visible.map((course, index) => (
                <Link className="course-card" href={`/courses/${course.id}`} key={course.id}>
                  <div className={`course-cover tint-${course.color}`}>
                    <BookOpen size={34} strokeWidth={1.2} />
                    <span className="cover-index">{String(index + 1).padStart(2, "0")}</span>
                    <div className="cover-lines" aria-hidden="true" />
                  </div>
                  <div className="course-card-body">
                    <div className="course-card-title">
                      <h2>{course.name}</h2>
                      <ArrowRight size={16} />
                    </div>
                    {course.description && <p>{course.description}</p>}
                    <div className="course-card-meta">
                      <span>
                        <FileText size={13} />
                        {course.document_count} 份课件
                      </span>
                      <span>{formatDate(course.updated_at)} 更新</span>
                    </div>
                  </div>
                </Link>
              ))}
              <button className="add-course-card" onClick={() => setCreateOpen(true)}>
                <span>
                  <Plus size={21} />
                </span>
                新建课程
              </button>
            </div>
          )}
        </>
      )}
      {createOpen && (
        <CourseForm
          onClose={() => setCreateOpen(false)}
          onSaved={async () => {
            await refresh();
            setCreateOpen(false);
          }}
        />
      )}
    </>
  );
}
