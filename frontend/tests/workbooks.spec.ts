import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";

async function prepare(page: Page) {
  await page.request.post("/api/auth/register", {
    data: {
      name: "习题整理",
      email: `workbook-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "线性代数", color: "sage" } })
  ).json();
  const pdf = Buffer.from(
    "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R 4 0 R]/Count 2>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<<>>>>endobj\n4 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<<>>>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF",
  );
  const uploaded = await page.request.post(`/api/courses/${course.id}/documents`, {
    multipart: { file: { name: "第一章课件.pdf", mimeType: "application/pdf", buffer: pdf } },
  });
  expect(uploaded.status()).toBe(201);
  const document = await uploaded.json();
  const seeded = await page.request.post(
    `http://127.0.0.1:8001/__test/documents/${document.id}/workbook-exercises`,
  );
  expect(seeded.status()).toBe(200);
  return { course, document };
}

test("原题筛选、分组排序、编辑保存及真实 PDF 下载", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const { course } = await prepare(page);
  await page.goto(`/courses/${course.id}`);
  await page.getByRole("link", { name: "课件做题本", exact: true }).click();
  await expect(page.getByRole("heading", { name: "课件做题本", exact: true })).toBeVisible();
  const picker = page.getByRole("region", { name: "课件题目", exact: true });
  const editor = page.getByRole("region", { name: "做题本内容", exact: true });
  await expect(picker).toContainText("找到 3 道课件题目");
  const sources = page.getByRole("region", { name: "来源课件与选题范围", exact: true });
  await sources.getByText("限定章节或页码（可选）", { exact: true }).click();
  await sources.getByLabel("起始页").fill("1");
  await sources.getByLabel("结束页").fill("1");
  await picker.getByRole("button", { name: "筛选题目" }).click();
  await expect(picker).toContainText("找到 2 道课件题目");
  await picker.getByRole("checkbox", { name: "分式计算", exact: true }).check();
  await picker.getByRole("checkbox", { name: "线性方程", exact: true }).check();
  await page.getByLabel("做题本名称", { exact: true }).fill("第一章计算练习");
  await editor.getByLabel("章节 / 分组名称").fill("第一节 分式与方程");
  await expect(editor.locator(".katex").first()).toBeVisible();
  await editor.getByRole("button", { name: "上移 线性方程", exact: true }).click();
  await expect(editor.locator(".workbook-selected").first()).toContainText("线性方程");
  await editor
    .locator(".workbook-selected")
    .first()
    .getByRole("button", { name: "编辑题目" })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("参考答案", { exact: true }).fill("$x = 2$，已核对。");
  await dialog.getByRole("button", { name: "应用到本册" }).click();
  await editor.getByRole("button", { name: "添加章节分组" }).click();
  await editor
    .getByRole("region", { name: "分组 2", exact: true })
    .getByLabel("章节 / 分组名称")
    .fill("第二节 讨论题");
  await sources.getByLabel("结束页").fill("2");
  await picker.getByRole("button", { name: "筛选题目" }).click();
  await expect(picker).toContainText("找到 3 道课件题目");
  await picker.getByRole("checkbox", { name: "无答案习题", exact: true }).check();
  await editor.getByRole("button", { name: "保存做题本", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("做题本已保存");
  const books = await (await page.request.get(`/api/courses/${course.id}/workbooks`)).json();
  const book = await (
    await page.request.get(`/api/courses/${course.id}/workbooks/${books[0].id}`)
  ).json();
  expect(book.sections[0].items[0].title).toBe("线性方程");
  expect(book.sections[0].items[0].answer).toContain("已核对");
  expect(book.sections[1].items[0].answer).toBe("");
  const preview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(preview, { recursive: true });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: path.join(preview, "workbooks.png"),
    fullPage: true,
    animations: "disabled",
  });
  const downloadEvent = page.waitForEvent("download");
  await editor.getByRole("button", { name: "保存并导出 PDF", exact: true }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("第一章计算练习.pdf");
  const downloadPath = path.join(preview, "workbook-sample.pdf");
  await download.saveAs(downloadPath);
  expect(readFileSync(downloadPath).subarray(0, 5).toString()).toBe("%PDF-");
  await expect(page.getByRole("status")).toContainText("PDF 已生成");
  await page.reload();
  await page.getByLabel("已保存的做题本", { exact: true }).selectOption(book.id);
  await expect(page.getByLabel("做题本名称", { exact: true })).toHaveValue("第一章计算练习");
  await expect(editor).toContainText("3 / 100 题");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "关闭导航", exact: true })).not.toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(preview, "workbooks-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  expect(errors).toEqual([]);
});

test("未保存切换提示、保存冲突及删除本册", async ({ page }) => {
  const { course } = await prepare(page);
  await page.goto(`/courses/${course.id}/workbooks`);
  const picker = page.getByRole("region", { name: "课件题目", exact: true });
  const editor = page.getByRole("region", { name: "做题本内容", exact: true });
  await picker.getByRole("checkbox", { name: "分式计算", exact: true }).check();
  await page.getByRole("button", { name: "新建", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("放弃未保存的修改");
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await editor.getByRole("button", { name: "保存做题本", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("做题本已保存");
  const books = await (await page.request.get(`/api/courses/${course.id}/workbooks`)).json();
  const path = `/api/courses/${course.id}/workbooks/${books[0].id}`;
  const book = await (await page.request.get(path)).json();
  const updated = await page.request.put(path, {
    data: { ...book, expected_version: book.version, title: "另一个标签页的标题" },
  });
  expect(updated.status()).toBe(200);
  await page.getByLabel("做题本名称", { exact: true }).fill("本页标题");
  await editor.getByRole("button", { name: "保存做题本", exact: true }).click();
  await expect(page.locator(".notice")).toContainText("做题本已被更新");
  expect((await (await page.request.get(path)).json()).title).toBe("另一个标签页的标题");
  await editor.getByRole("button", { name: "删除本册", exact: true }).click();
  await page.getByRole("button", { name: "确认删除做题本", exact: true }).click();
  await expect(editor).toContainText("0 / 100 题");
  expect((await page.request.get(path)).status()).toBe(404);
  expect((await (await page.request.get(`/api/courses/${course.id}/exercises`)).json()).total).toBe(
    3,
  );
});
