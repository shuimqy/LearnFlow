"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ChevronRight,
  FolderClosed,
  History,
  Layers2,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings,
  X,
} from "lucide-react";
import { api, errorMessage } from "@/lib/http";
import { CourseProvider, useCourses } from "@/features/courses/course-provider";
import { useAuth } from "@/features/auth/auth-provider";
import { CourseForm } from "@/features/courses/components/course-form";
import { Notice, Spinner } from "@/components/ui";
import { useStoredBoolean } from "@/lib/use-stored-boolean";

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const { user, loading, error, reload } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !user && !error) router.replace("/login");
  }, [loading, user, error, router]);
  if (loading)
    return (
      <div className="full-state">
        <Spinner />
      </div>
    );
  if (error)
    return (
      <div className="full-state">
        <Notice message={error} retry={() => void reload()} />
      </div>
    );
  if (!user)
    return (
      <div className="full-state">
        <Spinner label="正在前往登录页" />
      </div>
    );
  return (
    <CourseProvider>
      <ShellContent>{children}</ShellContent>
    </CourseProvider>
  );
}

function ShellContent({ children }: { children: React.ReactNode }) {
  const { user, setUser } = useAuth();
  const { courses, refresh } = useCourses();
  const [createOpen, setCreateOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [navigationCollapsed, setNavigationCollapsed] = useStoredBoolean(
    "learnflow.navigation-collapsed",
  );
  const [logoutError, setLogoutError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const path = usePathname();
  const isChat = /^\/courses\/[^/]+\/chat\/?$/.test(path);
  const router = useRouter();
  const course = courses.find(
    (item) => path === `/courses/${item.id}` || path.startsWith(`/courses/${item.id}/`),
  );
  useEffect(() => {
    setMobileOpen(false);
  }, [path]);
  async function logout() {
    setLoggingOut(true);
    try {
      await api("/auth/logout", { method: "POST" });
      setUser(null);
      router.replace("/login");
    } catch (err) {
      setLogoutError(errorMessage(err));
      setLoggingOut(false);
    }
  }
  return (
    <div className={`workspace${navigationCollapsed ? " navigation-collapsed" : ""}`}>
      {mobileOpen && (
        <button
          className="sidebar-scrim"
          aria-label="关闭导航"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        id="workspace-sidebar"
        aria-label="主导航"
        className={`sidebar ${mobileOpen ? "is-open" : ""}`}
      >
        <Link href="/" className="brand">
          <span className="brand-mark">
            <Layers2 size={21} strokeWidth={1.8} />
          </span>
          <span>
            LearnFlow<span className="brand-period">.</span>
          </span>
        </Link>
        <button
          className="icon-button mobile-close"
          aria-label="关闭导航"
          onClick={() => setMobileOpen(false)}
        >
          <X size={20} />
        </button>
        <div className="workspace-label">个人工作空间</div>
        <nav className="main-nav" aria-label="工作空间导航">
          <Link href="/" className={`nav-link ${path === "/" || course ? "active" : ""}`}>
            <FolderClosed size={18} />
            <span>我的课程</span>
            <span className="nav-count">{courses.length}</span>
          </Link>
          <Link href="/tasks" className={`nav-link ${path === "/tasks" ? "active" : ""}`}>
            <History size={18} />
            <span>处理记录</span>
          </Link>
          <Link href="/settings" className={`nav-link ${path === "/settings" ? "active" : ""}`}>
            <Settings size={18} />
            <span>账号设置</span>
          </Link>
        </nav>
        <div className="sidebar-section-title">
          <span>课程</span>
          <button className="icon-button" aria-label="新建课程" onClick={() => setCreateOpen(true)}>
            <Plus size={15} />
          </button>
        </div>
        <nav className="course-nav" aria-label="课程导航">
          {courses.slice(0, 8).map((item) => (
            <Link
              key={item.id}
              href={`/courses/${item.id}`}
              className={`course-nav-link ${course?.id === item.id ? "selected" : ""}`}
            >
              <span className={`course-dot dot-${item.color}`} />
              <span>{item.name}</span>
            </Link>
          ))}
          {!courses.length && <p className="sidebar-empty">创建课程后会显示在这里</p>}
        </nav>
        <div className="sidebar-bottom">
          {logoutError && <Notice message={logoutError} />}
          <div className="user-row">
            <span className="avatar">{user?.name.slice(0, 1)}</span>
            <Link href="/settings" className="user-copy" aria-label="打开账号设置">
              <strong>{user?.name}</strong>
              <span>个人空间</span>
            </Link>
            <button
              className="icon-button"
              aria-label="退出登录"
              title="退出登录"
              onClick={() => void logout()}
              disabled={loggingOut}
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className={`workspace-body${isChat ? " chat-workspace" : ""}`}>
        <header className="topbar">
          <button
            type="button"
            className="icon-button workspace-navigation-toggle"
            aria-label={navigationCollapsed ? "展开主导航" : "收起主导航"}
            title={navigationCollapsed ? "展开主导航" : "收起主导航"}
            aria-expanded={!navigationCollapsed}
            aria-controls="workspace-sidebar"
            onClick={() => setNavigationCollapsed(!navigationCollapsed)}
          >
            {navigationCollapsed ? <PanelLeftOpen size={19} /> : <PanelLeftClose size={19} />}
          </button>
          <button
            className="icon-button mobile-menu"
            aria-label="打开导航"
            onClick={() => setMobileOpen(true)}
          >
            <Menu size={20} />
          </button>
          <div className="breadcrumbs">
            <span>工作空间</span>
            <ChevronRight size={13} />
            {course ? (
              <>
                <Link href="/">我的课程</Link>
                <ChevronRight size={13} />
                <span className="breadcrumb-current">{course.name}</span>
              </>
            ) : (
              <span className="breadcrumb-current">
                {path === "/tasks" ? "处理记录" : path === "/settings" ? "账号设置" : "我的课程"}
              </span>
            )}
          </div>
          <span className="topbar-link">课程工作台</span>
        </header>
        <main className={`main-content${isChat ? " chat-workspace-content" : ""}`}>{children}</main>
      </div>
      {createOpen && (
        <CourseForm
          onClose={() => setCreateOpen(false)}
          onSaved={async (result) => {
            await refresh();
            setCreateOpen(false);
            router.push(`/courses/${result.id}`);
          }}
        />
      )}
    </div>
  );
}
