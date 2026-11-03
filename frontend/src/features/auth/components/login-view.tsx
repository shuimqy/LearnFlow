"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Layers2, LoaderCircle } from "lucide-react";
import { useAuth } from "@/features/auth/auth-provider";
import { Notice, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/http";
import type { User } from "@/features/auth/types";

export default function LoginPage() {
  const { user, setUser, loading } = useAuth();
  const router = useRouter();
  const [register, setRegister] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [user, loading, router]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<User>(`/auth/${register ? "register" : "login"}`, {
        method: "POST",
        body: JSON.stringify({ email, password, ...(register ? { name: name.trim() } : {}) }),
      });
      setUser(result);
      router.replace("/");
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }
  if (loading || user) {
    return (
      <main className="full-state">
        <Spinner label="正在进入工作空间" />
      </main>
    );
  }
  return (
    <main className="auth-page">
      <section className="auth-form-panel">
        <div className="auth-form-wrap">
          <div className="brand">
            <span className="brand-mark">
              <Layers2 size={21} strokeWidth={1.8} />
            </span>
            <span>
              LearnFlow<span className="brand-period">.</span>
            </span>
          </div>
          <h1>{register ? "创建账户" : "登录"}</h1>
          <form className="form-stack auth-form" onSubmit={submit}>
            {register && (
              <label>
                称呼
                <input
                  required
                  maxLength={80}
                  autoComplete="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="怎么称呼你"
                />
              </label>
            )}
            <label>
              邮箱
              <input
                type="email"
                required
                maxLength={254}
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
              />
            </label>
            <label>
              密码
              <input
                type="password"
                required
                minLength={8}
                maxLength={128}
                autoComplete={register ? "new-password" : "current-password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={register ? "至少 8 个字符" : "输入你的密码"}
              />
            </label>
            {error && <Notice message={error} />}
            <button className="button primary auth-submit" disabled={busy}>
              {busy ? <LoaderCircle size={17} className="spin" /> : null}
              {register ? "创建账户" : "登录"}
              {!busy && <ArrowRight size={17} />}
            </button>
          </form>
          <p className="auth-switch">
            {register ? "已经有账户？" : "第一次使用？"}
            <button
              className="text-button"
              disabled={busy}
              onClick={() => {
                setRegister(!register);
                setError("");
              }}
            >
              {register ? "直接登录" : "创建账户"}
            </button>
          </p>
          <p className="auth-privacy">课程资料保存在你的个人空间，仅本人可访问。</p>
        </div>
      </section>
    </main>
  );
}
