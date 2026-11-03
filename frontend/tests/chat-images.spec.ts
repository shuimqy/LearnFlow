import { expect, test } from "@playwright/test";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";

const image = {
  name: "题目截图.png",
  mimeType: "image/png",
  buffer: readFileSync(path.resolve(__dirname, "fixtures/chat-rectangle.png")),
};

test.beforeEach(async ({ page }) => {
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `chat-images-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "工程优化", color: "sage" } })
  ).json();
  await page.goto(`/courses/${course.id}/chat`);
});

test("图片上传、预览移除、只发图片、刷新恢复、图片分支和手机布局", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const input = page.getByLabel("添加图片", { exact: true });
  await input.setInputFiles(image);
  await expect(page.locator(".chat-image-drafts img")).toHaveCount(1);
  await page.getByRole("button", { name: "移除图片 题目截图.png" }).click();
  await expect(page.getByLabel("待发送图片")).toHaveCount(0);
  await input.setInputFiles(image);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const main = page.getByRole("region", { name: "课程对话", exact: true });
  const answer = main.locator(".chat-message.assistant");
  await expect(answer).toContainText("矩形面积");
  await expect(answer).toContainText("根据图片分析");
  await expect(answer.locator(".chat-citations")).toHaveCount(0);
  await expect(page.getByLabel("待发送图片")).toHaveCount(0);
  const thumbnail = main.getByRole("button", { name: "查看图片 1：题目截图.png" });
  await thumbnail.click();
  const preview = page.getByRole("dialog", { name: "查看图片", exact: true });
  await expect(preview.locator("img")).toBeVisible();
  await preview.getByRole("button", { name: "关闭", exact: true }).click();
  await page.reload();
  await expect(thumbnail).toBeVisible();
  const pictureUrl = await thumbnail.getByRole("img").getAttribute("src");
  expect((await page.request.get(pictureUrl!)).status()).toBe(200);
  await answer.getByRole("button", { name: "分支提问", exact: true }).click();
  await page.getByRole("textbox", { name: "分支问题" }).fill("图里的条件是什么意思？");
  await page.getByRole("button", { name: "创建并提问" }).click();
  const drawer = page.getByRole("dialog", { name: "分支提问", exact: true });
  await expect(drawer.locator(".chat-message.assistant")).toContainText("根据图片分析");
  await drawer.locator(".branch-context summary").click();
  await expect(drawer.locator(".branch-context").getByRole("img")).toBeVisible();
  await drawer.locator(".branch-context summary").click();
  await drawer
    .getByLabel("添加分支图片", { exact: true })
    .setInputFiles({ ...image, name: "第二张图.png" });
  await drawer.getByRole("textbox", { name: "在分支中继续提问" }).fill("再看看这张图");
  await drawer.getByRole("button", { name: "发送", exact: true }).click();
  await expect(drawer.locator(".chat-message.assistant")).toHaveCount(2);
  await expect(drawer.locator(".chat-message.assistant").last()).toContainText("矩形面积");
  await expect(drawer.getByRole("button", { name: "查看图片 1：第二张图.png" })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(drawer.getByRole("button", { name: "发送", exact: true })).toBeInViewport();
  expect(await drawer.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  const previews = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(previews, { recursive: true });
  await page.screenshot({ path: path.join(previews, "chat-images-mobile.png") });
  await drawer.getByRole("button", { name: "返回主对话" }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: path.join(previews, "chat-images.png") });
  await page.getByRole("button", { name: "删除对话 图片提问", exact: true }).click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(main.locator("img")).toHaveCount(0);
  expect((await page.request.get(pictureUrl!)).status()).toBe(404);
  expect(errors).toEqual([]);
});

test("粘贴图片，断网保留草稿并可重试", async ({ page }) => {
  const question = page.getByRole("textbox", { name: "向课程助手提问" });
  await question.evaluate((element, base64) => {
    const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
    const clipboard = new DataTransfer();
    clipboard.items.add(new File([bytes], "粘贴图片.png", { type: "image/png" }));
    element.dispatchEvent(
      new ClipboardEvent("paste", { clipboardData: clipboard, bubbles: true, cancelable: true }),
    );
  }, image.buffer.toString("base64"));
  await expect(page.locator(".chat-image-drafts img")).toHaveCount(1);
  await question.fill("请看图里的题目");
  await page.route("**/messages/with-images", (route) => route.abort("connectionfailed"));
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".notice")).toContainText("连接中断");
  await expect(question).toHaveValue("请看图里的题目");
  await expect(page.locator(".chat-image-drafts img")).toHaveCount(1);
  await page.unroute("**/messages/with-images");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".chat-message.assistant")).toContainText("矩形面积");
  await expect(page.locator(".chat-message.user")).toHaveCount(1);
});

test("图片限制和非视觉模型提示", async ({ page }) => {
  const input = page.getByLabel("添加图片", { exact: true });
  await input.setInputFiles(
    Array.from({ length: 5 }, (_, index) => ({ ...image, name: `${index}.png` })),
  );
  await expect(page.locator(".chat-upload-error")).toContainText("最多添加 4 张");
  await expect(page.getByLabel("待发送图片")).toHaveCount(0);
  await input.setInputFiles({
    name: "large.png",
    mimeType: "image/png",
    buffer: Buffer.alloc(5 * 1024 * 1024 + 1),
  });
  await expect(page.locator(".chat-upload-error")).toContainText("不能超过 5 MB");
  await page.route("**/retrieval/status", async (route) => {
    const response = await route.fetch();
    const state = await response.json();
    await route.fulfill({ response, json: { ...state, llm_vision: false } });
  });
  await page.reload();
  await input.setInputFiles(image);
  await expect(page.locator(".chat-upload-error")).toContainText("未启用图片识别");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "移除图片 题目截图.png" }).click();
  await page.getByRole("textbox", { name: "向课程助手提问" }).fill("纯文字仍然可以提问");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
});
