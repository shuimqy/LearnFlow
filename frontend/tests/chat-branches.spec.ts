import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

test.beforeEach(async ({ page }) => {
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `branches-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "线性代数", color: "sage" } })
  ).json();
  await page.request.post(`/api/courses/${course.id}/knowledge`, {
    data: {
      title: "线性无关的判断",
      content: "向量组线性无关，当且仅当零线性组合的系数全部为零。",
    },
  });
  await page.goto(`/courses/${course.id}/chat`);
  await page.getByRole("textbox", { name: "向课程助手提问" }).fill("线性无关的判断条件是什么？");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".chat-message.assistant .katex-display")).toBeVisible();
});

test("整条回答和选区创建分支，独立追问、刷新恢复、删除与手机布局", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  const main = page.getByRole("region", { name: "课程对话", exact: true });
  await main.getByRole("button", { name: "分支提问", exact: true }).click();
  const create = page.getByRole("dialog", { name: "创建分支提问", exact: true });
  await create.getByRole("textbox", { name: "分支问题" }).fill("线性无关条件为什么要求系数全零？");
  await create.getByRole("button", { name: "创建并提问" }).click();
  const drawer = page.getByRole("dialog", { name: "分支提问", exact: true });
  await expect(drawer.locator(".chat-message.assistant .katex-display")).toBeVisible();
  await expect(page).toHaveURL(/\?branch=/);
  await expect(drawer.getByRole("button", { name: "分支提问", exact: true })).toHaveCount(0);
  await drawer.locator(".branch-context summary").click();
  await expect(drawer.locator(".branch-context")).toContainText(
    "原问题：线性无关的判断条件是什么？",
  );
  await drawer.locator(".branch-context summary").click();
  await drawer
    .getByRole("textbox", { name: "在分支中继续提问" })
    .fill("线性无关条件能举个例子吗？");
  await drawer.getByRole("button", { name: "发送", exact: true }).click();
  await expect(drawer.locator(".chat-message.assistant .katex-display")).toHaveCount(2);
  await expect(main.locator(".chat-message.assistant")).toHaveCount(1);
  await page.reload();
  await expect(drawer.locator(".chat-message.assistant .katex-display")).toHaveCount(2);
  const previews = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(previews, { recursive: true });
  await page.screenshot({ path: path.join(previews, "chat-branch.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(drawer.getByRole("button", { name: "发送", exact: true })).toBeInViewport();
  expect(
    (await drawer.getByLabel("分支消息", { exact: true }).boundingBox())!.height,
  ).toBeGreaterThan(550);
  expect(await drawer.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: path.join(previews, "chat-branch-mobile.png") });
  await drawer.getByRole("button", { name: "返回主对话" }).click();
  await expect(drawer).toHaveCount(0);
  await expect(page).not.toHaveURL(/branch=/);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await main.getByRole("button", { name: "线性无关条件为什么要求系数全零？", exact: true }).click();
  await expect(drawer.locator(".chat-message.assistant")).toHaveCount(2);
  await drawer.getByRole("button", { name: "返回主对话" }).click();
  const selectedText = await main
    .locator(".chat-message.assistant .chat-answer-content")
    .first()
    .evaluate((element) => {
      const text = element.querySelector("p")!.firstChild!;
      const range = document.createRange();
      range.setStart(text, 0);
      range.setEnd(text, 8);
      const selection = window.getSelection()!;
      selection.removeAllRanges();
      selection.addRange(range);
      element.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
      return selection.toString();
    });
  await page.getByRole("button", { name: "针对选中内容提问" }).click();
  await expect(create.locator(".branch-anchor-preview")).toHaveText(selectedText);
  await create.getByRole("textbox", { name: "分支问题" }).fill("只解释线性无关的这个片段");
  await create.getByRole("combobox", { name: "上下文范围" }).selectOption("minimal");
  await create.getByRole("button", { name: "创建并提问" }).click();
  await expect(drawer.locator(".chat-message.assistant .katex-display")).toBeVisible();
  await drawer.locator(".branch-context summary").click();
  await expect(drawer.locator(".branch-anchor-preview")).toHaveText(selectedText);
  await drawer.getByRole("button", { name: "返回主对话" }).click();
  await main
    .getByRole("button", { name: "删除分支 只解释线性无关的这个片段", exact: true })
    .click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(
    main.getByRole("button", { name: "只解释线性无关的这个片段", exact: true }),
  ).toHaveCount(0);
  await expect(main.locator(".chat-message.assistant")).toHaveCount(1);
  await page
    .getByRole("button", { name: "删除对话 线性无关的判断条件是什么？", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("关联分支");
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(page.getByRole("heading", { name: "暂无消息", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("分支首个回答断网后可重试，创建不会重复", async ({ page }) => {
  await page.route("**/conversations/*/messages", async (route) => {
    if (route.request().method() === "POST") await route.abort("connectionfailed");
    else await route.continue();
  });
  await page.getByRole("button", { name: "分支提问", exact: true }).click();
  await page.getByRole("textbox", { name: "分支问题" }).fill("线性无关是什么？");
  await page.getByRole("button", { name: "创建并提问" }).click();
  const drawer = page.getByRole("dialog", { name: "分支提问", exact: true });
  await expect(drawer.getByRole("button", { name: "生成回答", exact: true })).toBeVisible();
  await expect(drawer.getByRole("textbox", { name: "在分支中继续提问" })).toBeDisabled();
  await page.unroute("**/conversations/*/messages");
  await drawer.getByRole("button", { name: "生成回答", exact: true }).click();
  await expect(drawer.locator(".chat-message.assistant .katex-display")).toBeVisible();
  await expect(drawer.locator(".chat-message")).toHaveCount(2);
  await drawer.getByRole("button", { name: "返回主对话" }).click();
  await expect(page.locator(".saved-branch")).toHaveCount(1);
});
