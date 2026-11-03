import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

function samplePdf() {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << >> >>",
  ];
  let data = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(data));
    data += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = Buffer.byteLength(data);
  data += `xref\n0 4\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(data);
}

test("课程问答、公式与来源、追问和独立会话历史", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `chat-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "线性代数", color: "sage" } })
  ).json();
  const uploaded = await page.request.post(`/api/courses/${course.id}/documents`, {
    multipart: {
      file: { name: "向量与线性方程.pdf", mimeType: "application/pdf", buffer: samplePdf() },
    },
  });
  expect(uploaded.status()).toBe(201);
  const document = await uploaded.json();
  const point = await (
    await page.request.post(`/api/courses/${course.id}/knowledge`, {
      data: {
        title: "线性无关的判断",
        summary: "向量组的零线性组合与系数条件",
        content: "向量组线性无关，当且仅当 $\\sum a_i v_i=0$ 的系数全部为零。",
        sources: [{ document_id: document.id, page_number: 1 }],
      },
    })
  ).json();
  await page.goto(`/courses/${course.id}`);
  await page.getByRole("link", { name: "课程问答", exact: true }).click();
  await expect(page.getByRole("heading", { name: "课程问答", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "暂无消息", exact: true })).toBeVisible();
  const question = page.getByRole("textbox", { name: "向课程助手提问" });
  const firstQuestion = "线性无关的判断条件是什么？";
  await question.fill(firstQuestion);
  await question.press("Enter");
  const answers = page.locator(".chat-message.assistant");
  await expect(answers).toHaveCount(1);
  await expect(answers.first().locator(".katex-display .katex")).toBeVisible();
  await expect(answers.first()).toContainText("补充解释");
  await expect(answers.first()).toContainText("关键词查找");
  const inlineCitation = answers.first().getByRole("link", { name: "K1", exact: true });
  await expect(inlineCitation).not.toHaveAttribute("target", "_blank");
  await inlineCitation.click();
  await answers.first().locator("summary").click();
  const source = answers.first().getByRole("link", { name: "向量与线性方程.pdf · 第 1 页" });
  await expect(source).toHaveAttribute("href", `/api/documents/${document.id}/file#page=1`);
  expect((await page.request.get(`/api/documents/${document.id}/file`)).status()).toBe(200);
  await expect(answers.first().getByRole("link", { name: "查看知识点" })).toHaveAttribute(
    "href",
    `/courses/${course.id}/knowledge?point=${point.id}`,
  );
  await question.fill("再解释一下这个条件");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(answers).toHaveCount(2);
  await expect(answers.last().locator(".katex-display .katex")).toBeVisible();
  await page.reload();
  await expect(answers).toHaveCount(2);
  const preview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(preview, { recursive: true });
  await page.screenshot({ path: path.join(preview, "chat.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "关闭导航" })).not.toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(preview, "chat-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  await expect(answers).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "暂无消息", exact: true })).toBeVisible();
  await question.fill("线性无关怎么判断？");
  await question.press("Enter");
  await expect(answers.first().locator(".katex-display .katex")).toBeVisible();
  const history = page.getByRole("complementary", { name: "问答历史" });
  await history.getByRole("button", { name: firstQuestion, exact: true }).click();
  await expect(answers).toHaveCount(2);
  await history.getByRole("button", { name: `删除对话 ${firstQuestion}`, exact: true }).click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(history.getByRole("button", { name: firstQuestion, exact: true })).toHaveCount(0);
  await history.getByRole("button", { name: "线性无关怎么判断？", exact: true }).click();
  await expect(answers).toHaveCount(1);
  await answers.first().locator("summary").click();
  await answers.first().getByRole("link", { name: "查看知识点" }).click();
  await expect(page.getByRole("region", { name: "知识点详情" })).toContainText("线性无关的判断");
  expect(errors).toEqual([]);
});

test("空知识库明确说明依据不足", async ({ page }) => {
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `chat-empty-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "空课程", color: "sage" } })
  ).json();
  await page.goto(`/courses/${course.id}/chat`);
  await page.getByRole("textbox", { name: "向课程助手提问" }).fill("本课程介绍了什么？");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const answer = page.locator(".chat-message.assistant");
  await expect(answer).toContainText("没有找到足够相关的依据");
  await expect(answer.locator(".chat-citation")).toHaveCount(0);
  await page.reload();
  await expect(answer).toContainText("没有找到足够相关的依据");
});

test("回顾上个问题不要求知识引用，刷新后保留回答", async ({ page }) => {
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `chat-recall-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "工程优化", color: "sage" } })
  ).json();
  await page.goto(`/courses/${course.id}/chat`);
  const question = page.getByRole("textbox", { name: "向课程助手提问" });
  await question.fill("介绍下凸函数的性质");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".chat-message.assistant")).toContainText("没有找到足够相关的依据");
  await question.fill("我知道了，，我上个问题是什么");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const answer = page.locator(".chat-message.assistant").last();
  await expect(answer).toContainText("你上一个问题是");
  await expect(answer.locator("blockquote")).toHaveText("介绍下凸函数的性质");
  await expect(answer.locator(".chat-citation, .chat-failed, .chat-warnings")).toHaveCount(0);
  await page.reload();
  await expect(answer.locator("blockquote")).toHaveText("介绍下凸函数的性质");
});

test("长回答使用完整阅读区，消息独立滚动，手机历史按需展开", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `chat-layout-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "线性代数", color: "sage" } })
  ).json();
  await page.request.post(`/api/courses/${course.id}/knowledge`, {
    data: { title: "长回答布局", content: "线性组合只有全零系数时得到零向量。" },
  });
  await page.goto(`/courses/${course.id}/chat`);
  await expect(page.getByRole("button", { name: "关闭对话历史", exact: true })).toBeHidden();
  await page.getByRole("textbox", { name: "向课程助手提问" }).fill("长回答布局");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".chat-message.assistant")).toContainText("第 24 步");
  const messages = page.getByLabel("对话消息", { exact: true });
  const send = page.getByRole("button", { name: "发送", exact: true });
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1366, height: 768 },
    { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    expect((await messages.boundingBox())!.height).toBeGreaterThan(viewport.height * 0.68);
    await expect(send).toBeInViewport();
    expect(
      await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1),
    ).toBe(true);
  }
  const historyPanel = page.getByRole("complementary", { name: "问答历史" });
  const mainPanel = page.getByRole("region", { name: "课程对话" });
  const originalWidth = (await mainPanel.boundingBox())!.width;
  const question = page.getByRole("textbox", { name: "向课程助手提问" });
  await question.fill("保留这条未发送的问题");
  await page.getByRole("button", { name: "收起对话历史", exact: true }).click();
  await expect(historyPanel).toBeHidden();
  expect((await mainPanel.boundingBox())!.width).toBeGreaterThan(originalWidth + 200);
  await page.getByRole("button", { name: "收起主导航", exact: true }).click();
  await expect(page.locator("#workspace-sidebar")).toBeHidden();
  expect((await mainPanel.boundingBox())!.width).toBeGreaterThan(1920 * 0.95);
  await expect(question).toHaveValue("保留这条未发送的问题");
  await expect(page.locator(".chat-message.assistant")).toContainText("第 24 步");
  await question.fill("");
  await page.reload();
  await expect(page.getByRole("button", { name: "展开主导航", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "展开对话历史", exact: true })).toBeVisible();
  await expect(historyPanel).toBeHidden();
  await expect(page.locator(".chat-message.assistant")).toContainText("第 24 步");
  expect((await mainPanel.boundingBox())!.width).toBeGreaterThan(1920 * 0.95);
  const widePreview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(widePreview, { recursive: true });
  await messages.evaluate((element) => element.scrollTo({ top: 0 }));
  await page.screenshot({ path: path.join(widePreview, "chat-full-width.png"), fullPage: true });
  await page.getByRole("button", { name: "展开主导航", exact: true }).click();
  await page.getByRole("button", { name: "展开对话历史", exact: true }).click();
  await expect(historyPanel).toBeVisible();
  await expect(page.locator("#workspace-sidebar")).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await messages.evaluate((element) => element.scrollTo({ top: 0 }));
  await messages.hover();
  await page.mouse.wheel(0, 450);
  await expect.poll(() => messages.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  expect(await page.evaluate(() => scrollY)).toBe(0);
  await expect(send).toBeInViewport();
  expect((await page.locator(".chat-composer").boundingBox())!.height).toBeLessThan(100);
  const preview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(preview, { recursive: true });
  await messages.evaluate((element) => element.scrollTo({ top: 0 }));
  await page.screenshot({ path: path.join(preview, "chat-reading.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "关闭导航" })).not.toBeInViewport();
  const history = page.getByRole("complementary", { name: "问答历史" });
  await expect(history).toBeHidden();
  expect((await messages.boundingBox())!.height).toBeGreaterThan(844 * 0.65);
  await expect(send).toBeInViewport();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollHeight <= innerHeight + 1 &&
        document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "历史对话", exact: true }).click();
  await expect(history).toBeVisible();
  await history.getByRole("button", { name: "长回答布局", exact: true }).click();
  await expect(history).toBeHidden();
  await page.screenshot({
    path: path.join(preview, "chat-reading-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
});

test("按需检索：交流、回顾、复用依据、更新后重新查找和澄清", async ({ page }) => {
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `chat-routing-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "线性代数", color: "sage" } })
  ).json();
  const point = await (
    await page.request.post(`/api/courses/${course.id}/knowledge`, {
      data: {
        title: "线性无关的判断",
        content: "向量组线性无关，当且仅当零线性组合的系数全部为零。",
      },
    })
  ).json();
  await page.goto(`/courses/${course.id}/chat`);
  const question = page.getByRole("textbox", { name: "向课程助手提问" });
  const answers = page.locator(".chat-message.assistant");
  async function ask(text: string, expected: string) {
    await question.fill(text);
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect(answers.last()).toContainText(expected);
    await expect(question).toBeEnabled();
  }
  await ask("先缓一缓，今天有点学不动", "可以先休息一下");
  await expect(answers.last().locator(".chat-citation, .chat-warnings")).toHaveCount(0);
  await expect(answers.last()).toContainText("根据对话上下文");
  await ask("线性无关的判断条件是什么？", "系数全部为零");
  await expect(answers.last().locator(".chat-citation")).toHaveCount(1);
  await ask("把刚才的判断条件说简单一点", "沿用对话中的课程依据");
  await expect(answers.last().locator(".chat-citation")).toHaveCount(1);
  await expect(answers.last().locator(".chat-warnings")).toHaveCount(0);
  await ask("把我们刚才聊的内容总结一下", "我们刚才讨论了");
  await expect(answers.last().locator(".chat-citation, .chat-warnings")).toHaveCount(0);
  await page.request.patch(`/api/courses/${course.id}/knowledge/${point.id}`, {
    data: {
      title: point.title,
      summary: "",
      content: "线性无关的最新定义：零线性组合只有全零系数。",
      sources: [],
      expected_version: 1,
      reason: "更新定义",
    },
  });
  await ask("把刚才的判断条件说简单一点", "系数全部为零");
  await expect(answers.last()).not.toContainText("沿用对话中的课程依据");
  await expect(answers.last().locator(".chat-citation")).toContainText("第 2 版");
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  await ask("这个怎么算", "请补充题目或具体步骤");
  await expect(answers.last()).toContainText("需要补充问题信息");
  await expect(answers.last().locator(".chat-citation, .chat-warnings")).toHaveCount(0);
});
