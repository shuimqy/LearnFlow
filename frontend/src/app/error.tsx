"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <div className="plain-empty">
      <h2>页面暂时无法显示</h2>
      <p>请重试，已保存的课程资料不会受到影响。</p>
      <button className="button secondary" onClick={reset}>
        重新加载
      </button>
    </div>
  );
}
