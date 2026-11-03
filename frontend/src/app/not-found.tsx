import Link from "next/link";

export default function NotFound() {
  return (
    <main className="full-state">
      <div className="plain-empty">
        <span className="eyebrow">404</span>
        <h1>页面不存在</h1>
        <p>页面可能已移动，回到课程列表继续。</p>
        <Link href="/" className="button primary">
          返回我的课程
        </Link>
      </div>
    </main>
  );
}
