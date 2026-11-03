import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

async function prepare(page: Page) {
  await page.request.post("/api/auth/register", {
    data: {
      name: "章节练习",
      email: `organized-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "线性代数", color: "sage" } })
  ).json();
  const pdf = await page.request.get("http://127.0.0.1:8001/__test/workbook-source.pdf");
  expect(pdf.status()).toBe(200);
  const document = await (
    await page.request.post(`/api/courses/${course.id}/documents`, {
      multipart: {
        file: { name: "章节课件.pdf", mimeType: "application/pdf", buffer: await pdf.body() },
      },
    })
  ).json();
  expect(
    (
      await page.request.post(
        `http://127.0.0.1:8001/__test/documents/${document.id}/workbook-exercises?organized=true`,
      )
    ).status(),
  ).toBe(200);
  await page.goto(`/courses/${course.id}/workbooks`);
  return { course, document };
}

test("章节编辑、按章规则选题、自然语言选题与缺题报告", async ({ page }) => {
  const { course, document } = await prepare(page);
  const detailEvent = page.waitForEvent("popup");
  await page.getByRole("link", { name: "管理章节 ↗", exact: true }).click();
  const detail = await detailEvent;
  await expect(detail.getByRole("heading", { name: "课件详情", exact: true })).toBeVisible();
  const organizer = detail
    .locator(".chapter-organizer")
    .filter({ has: detail.getByText("章节与原题整理", { exact: true }) });
  await expect(organizer.getByLabel("章节 1 名称", { exact: true })).toHaveValue("第一章 基本运算");
  await organizer.getByLabel("章节 1 名称", { exact: true }).fill("第一章 分式与方程");
  await organizer.getByRole("button", { name: "保存章节", exact: true }).click();
  await expect(organizer.getByRole("status")).toContainText("章节已保存");
  mkdirSync(path.resolve(__dirname, "../../.local/previews"), { recursive: true });
  await detail.screenshot({
    path: path.resolve(__dirname, "../../.local/previews/document-chapters.png"),
    fullPage: true,
    animations: "disabled",
  });
  await detail.close();
  await page.bringToFront();
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  const sources = page.getByRole("region", { name: "来源课件与选题范围", exact: true });
  await sources.getByText("限定章节或页码（可选）", { exact: true }).click();
  await sources.getByRole("checkbox", { name: /第二章 向量/ }).check();
  await expect(page.locator(".workbook-result-count")).toContainText("找到 1 道");
  await sources.getByRole("button", { name: "清除章节限制", exact: true }).click();
  const assembly = page
    .locator(".workbook-tool-panel")
    .filter({ has: page.getByText("按要求自动整理做题本", { exact: true }) });
  await assembly.locator(":scope > summary").click();
  await assembly.getByLabel("总题数", { exact: true }).fill("4");
  await assembly.getByRole("button", { name: "自动选题并预览" }).click();
  await expect(assembly).toContainText("需要 4 题，已选 3 题，还缺 1 题");
  await expect(assembly).toContainText("没有用新题补足");
  await assembly.getByRole("button", { name: "作为新做题本打开" }).click();
  const editor = page.getByRole("region", { name: "做题本内容", exact: true });
  await expect(editor).toContainText("3 / 100 题");
  await editor.getByRole("button", { name: "保存做题本", exact: true }).click();
  await expect(page.locator(".success-notice")).toContainText("做题本已保存");
  await assembly.getByLabel("总题数", { exact: true }).fill("");
  await assembly.getByLabel("整理要求", { exact: true }).fill("第一章选两个计算题，覆盖主要知识点");
  await assembly.getByRole("button", { name: "自动选题并预览" }).click();
  await expect(assembly).toContainText("需要 2 题，已选 2 题");
  await expect(assembly).toContainText("覆盖已有计算题");
  await assembly.getByRole("button", { name: "作为新做题本打开" }).click();
  await expect(editor).toContainText("2 / 100 题");
  await expect(editor.getByLabel("章节 / 分组名称")).toHaveValue("第一章 分式与方程");
  const preview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(preview, { recursive: true });
  await page.screenshot({
    path: path.join(preview, "workbook-organization.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(preview, "workbook-organization-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  expect(
    (await (await page.request.get(`/api/courses/${course.id}/workbooks`)).json()).length,
  ).toBe(1);
});

test("多选来源课件，手动与自动选题共用范围且保留本册", async ({ page }) => {
  const { course, document } = await prepare(page);
  const pdf = await page.request.get("http://127.0.0.1:8001/__test/workbook-source.pdf");
  const uploaded = await page.request.post(`/api/courses/${course.id}/documents`, {
    multipart: {
      file: { name: "第二份课件.pdf", mimeType: "application/pdf", buffer: await pdf.body() },
    },
  });
  expect(uploaded.status()).toBe(201);
  const second = await uploaded.json();
  expect(
    (
      await page.request.post(
        `http://127.0.0.1:8001/__test/documents/${second.id}/workbook-exercises?organized=true`,
      )
    ).status(),
  ).toBe(200);
  await page.reload();
  const sources = page.getByRole("region", { name: "来源课件与选题范围", exact: true });
  const entry = sources.getByRole("link", { name: "手动挑选题目 ↓", exact: true });
  await expect(
    sources.getByRole("heading", { name: "1. 选择来源课件", exact: true }),
  ).toBeInViewport();
  await entry.click();
  await expect(
    page.getByRole("heading", { name: "2. 手动选择原题", exact: true }),
  ).toBeInViewport();
  const picker = page.getByRole("region", { name: "课件题目", exact: true });
  await sources.getByRole("checkbox", { name: "第二份课件.pdf 2 页", exact: true }).uncheck();
  await sources.getByText("限定章节或页码（可选）", { exact: true }).click();
  await sources.getByRole("checkbox", { name: /第一章 基本运算/ }).check();
  await expect(picker).toContainText("找到 2 道课件题目");
  await picker.getByRole("checkbox", { name: "分式计算", exact: true }).check();
  await sources.getByRole("checkbox", { name: "章节课件.pdf 2 页", exact: true }).uncheck();
  await expect(picker).toContainText("请先选择来源课件");
  await sources.getByRole("checkbox", { name: "第二份课件.pdf 2 页", exact: true }).check();
  await expect(picker).toContainText("找到 3 道课件题目");
  await picker.getByRole("checkbox", { name: "线性方程", exact: true }).check();
  const editor = page.getByRole("region", { name: "做题本内容", exact: true });
  await expect(editor).toContainText("2 / 100 题");
  await editor.getByRole("button", { name: "保存做题本", exact: true }).click();
  await expect(page.locator(".success-notice")).toContainText("做题本已保存");
  const books = await (await page.request.get(`/api/courses/${course.id}/workbooks`)).json();
  const book = await (
    await page.request.get(`/api/courses/${course.id}/workbooks/${books[0].id}`)
  ).json();
  expect(
    book.sections.flatMap((group: { items: { document_id: string }[] }) =>
      group.items.map((item) => item.document_id),
    ),
  ).toEqual([document.id, second.id]);
  await sources.getByRole("button", { name: "全选课件", exact: true }).click();
  const assembly = page
    .locator(".workbook-tool-panel")
    .filter({ has: page.getByText("按要求自动整理做题本", { exact: true }) });
  await assembly.locator(":scope > summary").click();
  await assembly.getByLabel("选题方式", { exact: true }).selectOption("all");
  await assembly.getByRole("button", { name: "自动选题并预览", exact: true }).click();
  await expect(assembly).toContainText("范围内 6 道候选题");
  await sources.getByRole("checkbox", { name: "章节课件.pdf 2 页", exact: true }).uncheck();
  await expect(assembly.getByRole("button", { name: "作为新做题本打开", exact: true })).toHaveCount(
    0,
  );
  await assembly.getByRole("button", { name: "自动选题并预览", exact: true }).click();
  await expect(assembly).toContainText("范围内 3 道候选题");
  const structure = await (await page.request.get(`/api/documents/${second.id}/structure`)).json();
  const revised = await page.request.put(`/api/documents/${second.id}/chapters`, {
    data: {
      expected_version: structure.version,
      chapters: [{ ...structure.chapters[0], end_page: 2 }],
    },
  });
  expect(revised.status()).toBe(200);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(assembly.getByRole("button", { name: "作为新做题本打开", exact: true })).toHaveCount(
    0,
  );
  await sources.getByRole("checkbox", { name: /第一章 基本运算/ }).check();
  await expect(picker).toContainText("找到 3 道课件题目");
  const latest = await revised.json();
  expect(
    (
      await page.request.put(`/api/documents/${second.id}/chapters`, {
        data: { expected_version: latest.version, chapters: [] },
      })
    ).status(),
  ).toBe(200);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(picker).toContainText("所选章节已变更");
  await expect(
    assembly.getByRole("button", { name: "自动选题并预览", exact: true }),
  ).toBeDisabled();
  await sources.getByRole("button", { name: "清除章节限制", exact: true }).click();
  await expect(picker).toContainText("找到 3 道课件题目");
  await page.screenshot({
    path: path.resolve(__dirname, "../../.local/previews/workbook-sources.png"),
    fullPage: true,
    animations: "disabled",
  });
  await sources.getByRole("button", { name: "清空选择", exact: true }).click();
  await expect(
    assembly.getByRole("button", { name: "自动选题并预览", exact: true }),
  ).toBeDisabled();
  await expect(editor).toContainText("2 / 100 题");
});

test("全部原题、本地去重与顶部改名保留未保存题目", async ({ page }) => {
  const { course } = await prepare(page);
  await expect(page.getByText("章节与原题整理", { exact: true })).toHaveCount(0);
  const assembly = page.locator(".workbook-tool-panel").filter({
    has: page.getByText("按要求自动整理做题本", { exact: true }),
  });
  await assembly.locator(":scope > summary").click();
  await assembly.getByLabel("整理要求", { exact: true }).fill("所有题都要，但是把重复题去掉");
  await assembly.getByRole("button", { name: "自动选题并预览" }).click();
  await expect(assembly).toContainText("已整理全部原题，共 3 题");
  await expect(assembly).toContainText("已在本地完成整理");
  await assembly.getByLabel("整理要求", { exact: true }).fill("");
  await assembly.getByLabel("选题方式", { exact: true }).selectOption("all");
  await expect(assembly.getByLabel("总题数", { exact: true })).not.toBeVisible();
  await assembly.getByRole("button", { name: "自动选题并预览" }).click();
  await expect(assembly).toContainText("已整理全部原题，共 3 题");
  await assembly.getByRole("button", { name: "作为新做题本打开" }).click();
  const editor = page.getByRole("region", { name: "做题本内容", exact: true });
  await editor.getByRole("button", { name: "保存做题本", exact: true }).click();
  await expect(page.locator(".success-notice")).toContainText("做题本已保存");
  await editor.getByLabel("章节 / 分组名称").first().fill("尚未保存的分组编辑");
  await page.getByLabel("做题本名称", { exact: true }).fill("期末原题练习");
  await page.getByRole("button", { name: "保存名称", exact: true }).click();
  await expect(page.locator(".success-notice")).toContainText("做题本名称已保存");
  await expect(editor.getByLabel("章节 / 分组名称").first()).toHaveValue("尚未保存的分组编辑");
  await expect(page.locator(".workbook-save-state")).toContainText("有未保存的修改");
  const books = await (await page.request.get(`/api/courses/${course.id}/workbooks`)).json();
  const saved = await (
    await page.request.get(`/api/courses/${course.id}/workbooks/${books[0].id}`)
  ).json();
  expect(saved.title).toBe("期末原题练习");
  expect(saved.sections[0].title).not.toBe("尚未保存的分组编辑");
  await editor.getByRole("button", { name: "保存做题本", exact: true }).click();
  await expect(page.locator(".success-notice")).toContainText("做题本已保存");
  await page.reload();
  await page.getByLabel("已保存的做题本", { exact: true }).selectOption(saved.id);
  await expect(page.getByLabel("做题本名称", { exact: true })).toHaveValue("期末原题练习");
  await expect(editor.getByLabel("章节 / 分组名称").first()).toHaveValue("尚未保存的分组编辑");
  await expect(editor).toContainText("3 / 100 题");
});

test("在原页框选多区域、确认快照并下载保真 PDF", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const { course } = await prepare(page);
  const first = page
    .locator(".workbook-candidate")
    .filter({ has: page.getByRole("checkbox", { name: "分式计算", exact: true }) });
  await first.getByRole("button", { name: "核对裁片与标签", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const canvas = dialog.getByLabel("原页框选画布", { exact: true });
  await expect(canvas.locator("img")).toBeVisible();
  await expect
    .poll(() => canvas.locator("img").evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);
  await canvas.scrollIntoViewIfNeeded();
  let rect = await canvas.boundingBox();
  if (!rect) throw new Error("No crop canvas");
  await page.mouse.move(rect.x + rect.width * 0.05, rect.y + rect.height * 0.07);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width * 0.7, rect.y + rect.height * 0.25);
  await page.mouse.up();
  await expect(dialog.getByLabel("区域 1 左坐标", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "追加区域", exact: true }).click();
  await dialog.getByLabel("区域用途", { exact: true }).selectOption("figure");
  await canvas.scrollIntoViewIfNeeded();
  rect = await canvas.boundingBox();
  if (!rect) throw new Error("No crop canvas");
  await page.mouse.move(rect.x + rect.width * 0.27, rect.y + rect.height * 0.12);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width * 0.46, rect.y + rect.height * 0.21);
  await page.mouse.up();
  await expect(dialog.getByLabel("区域 2 左坐标", { exact: true })).toBeVisible();
  const preview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(preview, { recursive: true });
  await dialog.screenshot({
    path: path.join(preview, "workbook-crop-editor.png"),
    animations: "disabled",
  });
  await dialog.getByRole("checkbox", { name: "已核对完整原题和题图", exact: false }).check();
  await dialog.getByRole("button", { name: "确认并保存裁片", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(first.getByRole("button", { name: "查看裁片与标签", exact: true })).toBeVisible();
  await first.getByRole("checkbox", { name: "分式计算", exact: true }).check();
  const editor = page.getByRole("region", { name: "做题本内容", exact: true });
  await editor.getByLabel("打印方式", { exact: true }).selectOption("original");
  const downloadEvent = page.waitForEvent("download");
  await editor.getByRole("button", { name: "保存并导出 PDF", exact: true }).click();
  const download = await downloadEvent;
  await download.saveAs(path.join(preview, "workbook-original.pdf"));
  await expect(page.locator(".success-notice")).toContainText("PDF 已生成");
  const books = await (await page.request.get(`/api/courses/${course.id}/workbooks`)).json();
  const book = await (
    await page.request.get(`/api/courses/${course.id}/workbooks/${books[0].id}`)
  ).json();
  expect(book.sections[0].items[0].assets.length).toBe(2);
  expect(book.sections[0].items[0].asset_scope).toBe("workbook");
  expect(errors).toEqual([]);
});
