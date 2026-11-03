"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[
          [rehypeKatex, { trust: false, strict: "warn", throwOnError: false, maxExpand: 1000 }],
        ]}
        components={{
          img: ({ alt }) => <span>[图片：{alt || "请查看课件原页"}]</span>,
          a: ({ children, href }) => (
            <a
              href={href}
              target={href?.startsWith("#") ? undefined : "_blank"}
              rel={href?.startsWith("#") ? undefined : "noreferrer noopener"}
            >
              {children}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
