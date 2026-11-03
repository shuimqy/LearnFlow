import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { chromium } from "playwright";

const h = React.createElement;
const require = createRequire(import.meta.url);
const md = (text) =>
  h(
    ReactMarkdown,
    {
      skipHtml: true,
      remarkPlugins: [remarkGfm, remarkMath],
      rehypePlugins: [
        [rehypeKatex, { trust: false, strict: "ignore", throwOnError: false, maxExpand: 1000 }],
      ],
      components: {
        img: ({ alt }) => h("span", null, `[图片：${alt || "请对照课件原页"}]`),
        a: ({ children }) => h("span", null, children),
      },
    },
    text,
  );

export async function workbookHtml(book) {
  const katexDir = path.dirname(require.resolve("katex/dist/katex.min.css"));
  let katexCss = await readFile(path.join(katexDir, "katex.min.css"), "utf8");
  const urls = [
    ...new Set([...katexCss.matchAll(/url\((fonts\/[^)]+)\)/g)].map((match) => match[1])),
  ];
  for (const url of urls) {
    const data = await readFile(path.join(katexDir, url));
    const format = path.extname(url).slice(1);
    katexCss = katexCss.replaceAll(
      `url(${url})`,
      `url(data:font/${format};base64,${data.toString("base64")})`,
    );
  }
  let number = 0;
  const numbered = book.sections.map((group) => ({
    ...group,
    items: group.items.map((item) => ({ ...item, number: ++number })),
  }));
  const question = (item) =>
    h(
      "article",
      { className: "exercise", key: item.number },
      h("h3", null, `${item.number}. ${item.title}`),
      book.settings.show_sources &&
        h("p", { className: "source" }, `${item.filename} · 第 ${item.page_number} 页`),
      ...(book.settings.print_mode === "original"
        ? (item.question_images || []).map((url, index) =>
            h("img", { key: index, src: url, className: "original-crop", alt: "原题裁片" }),
          )
        : [
            md(item.question),
            ...(item.figures || []).map((url, index) =>
              h("img", { key: index, src: url, className: "figure-crop", alt: "原题题图" }),
            ),
          ]),
      item.warnings?.length > 0 &&
        h(
          "aside",
          { className: "warnings" },
          ...item.warnings.map((text, i) => h("div", { key: i }, `识别提示：${text}`)),
        ),
      h("div", {
        className: `answer-space ${book.settings.answer_space}`,
        "aria-label": "答题留白",
      }),
    );
  const answer = (item) =>
    h(
      "article",
      { className: "answer", key: item.number },
      h("h3", null, `${item.number}. ${item.title}`),
      h("h4", null, "参考答案"),
      md(item.answer.trim() || "课件未提供答案。"),
      h("h4", null, "解题步骤"),
      md(item.solution.trim() || "课件未提供解题步骤。"),
    );
  const body = renderToStaticMarkup(
    h(
      "main",
      null,
      h(
        "header",
        null,
        h("p", { className: "course" }, book.course_name),
        h("h1", null, book.title),
        h("p", null, `姓名：________________　日期：________________　共 ${number} 题`),
        h(
          "p",
          { className: "note" },
          book.settings.print_mode === "original"
            ? "按已确认原题裁片排版，保留原题样式；文字编辑仅用于文字重排版。"
            : "整理自课件识别结果。已确认的题图随题打印；尚未确认的题图请对照原页。",
        ),
      ),
      h(
        "div",
        { className: `questions ${book.settings.answer_space === "page" ? "one-per-page" : ""}` },
        ...numbered.map((group, i) =>
          h(
            "section",
            { className: "section", key: i },
            h("h2", null, group.title),
            ...group.items.map(question),
          ),
        ),
      ),
      book.settings.include_answers &&
        h(
          "div",
          { className: "answers" },
          h("h1", null, "参考答案与解析"),
          h(
            "p",
            { className: "note" },
            "未提供的答案和步骤保持为空，不自动补写。做题本中的编辑不回写知识库。",
          ),
          ...numbered.map((group, i) =>
            h("section", { key: i }, h("h2", null, group.title), ...group.items.map(answer)),
          ),
        ),
    ),
  );
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:"><style>${katexCss}
    @page { size: A4; margin: 18mm 18mm 20mm; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #202020; font: 11pt/1.8 "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif; overflow-wrap: anywhere; }
    h1 { font-size: 21pt; line-height: 1.4; margin: 0 0 6mm; }
    h2 { font-size: 15pt; border-bottom: 1px solid #777; padding-bottom: 2mm; margin: 8mm 0 5mm; }
    h3 { font-size: 11.5pt; margin: 0 0 2mm; }
    h4 { font-size: 10.5pt; margin: 3mm 0 1mm; }
    h1,h2,h3,h4 { break-after: avoid; }
    p { margin: 2mm 0; } header { margin-bottom: 8mm; }
    .course,.source,.note { color: #555; font-size: 9pt; }
    .source { margin-bottom: 3mm; } .warnings { font-size: 9pt; border-left: 2px solid #888; padding-left: 3mm; margin: 3mm 0; }
    .section + .section { break-before: page; }
    .exercise { break-inside: avoid; margin-bottom: 6mm; }
    .answer { margin: 0 0 8mm; } .answer-space { break-inside: avoid; }
    .answer-space.compact { height: 15mm; } .answer-space.medium { height: 45mm; } .answer-space.large { height: 85mm; } .answer-space.page { min-height: 110mm; }
    .one-per-page .exercise + .exercise { break-before: page; }
    .answers { break-before: page; }
    table { border-collapse: collapse; width: 100%; } th,td { border: 1px solid #999; padding: 2mm; } tr { break-inside: avoid; }
    pre { white-space: pre-wrap; background: #f5f5f5; padding: 3mm; } code { font-size: 9pt; }
    .katex { font-size: 1.05em; } .katex-display { overflow: visible; }
    .original-crop { display: block; max-width: 100%; max-height: 210mm; width: auto; height: auto; object-fit: contain; margin: 3mm 0; }
    .figure-crop { display: block; max-width: 100%; max-height: 95mm; object-fit: contain; margin: 3mm auto; }
  </style></head><body>${body}</body></html>`;
}

let browser;
const deadline = setTimeout(() => {
  void browser?.close().finally(() => process.exit(1));
  if (!browser) process.exit(1);
}, 75000);
try {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const book = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const html = await workbookHtml(book);
  browser = await chromium.launch({
    headless: true,
    ...(process.platform === "win32" ? { channel: "msedge" } : {}),
  });
  const context = await browser.newContext({ javaScriptEnabled: false, serviceWorkers: "block" });
  await context.route("**/*", (route) => route.abort());
  const page = await context.newPage();
  await page.setContent(html, { waitUntil: "load", timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  const pdf = await page.pdf({
    format: "A4",
    printBackground: true,
    preferCSSPageSize: true,
    displayHeaderFooter: true,
    headerTemplate: "<span></span>",
    footerTemplate:
      '<div style="font-size:9px;width:100%;text-align:center;color:#666"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
  });
  process.stdout.write(pdf);
} catch {
  process.stderr.write("Workbook PDF rendering failed.\n");
  process.exitCode = 1;
} finally {
  await browser?.close();
  clearTimeout(deadline);
}
