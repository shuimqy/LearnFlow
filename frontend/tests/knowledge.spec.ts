import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

function lecturePdf() {
  const text = "BT /F1 12 Tf 72 760 Td (Only the trivial linear combination is zero.) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(text)} >>\nstream\n${text}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let data = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(data));
    data += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = Buffer.byteLength(data);
  data += `xref\n0 6\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(data);
}

test("知识点引用、修订、确认纠错和归档恢复", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.request.post("/api/auth/register", {
    data: {
      email: `knowledge-${Date.now()}@example.com`,
      name: "小林",
      password: "course-notes-2026",
    },
  });
  const courseResponse = await page.request.post("/api/courses", {
    data: { name: "线性代数", description: "向量与线性变换", color: "sage" },
  });
  const course = await courseResponse.json();
  const uploaded = await page.request.post(`/api/courses/${course.id}/documents`, {
    multipart: {
      file: { name: "线性代数课件.pdf", mimeType: "application/pdf", buffer: lecturePdf() },
    },
  });
  expect(uploaded.status()).toBe(201);
  const base = `/api/courses/${course.id}/knowledge`;
  await page.goto(`/courses/${course.id}`);
  await page.getByRole("link", { name: "课程知识库" }).click();
  await expect(page.getByRole("heading", { name: "课程知识库", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "添加知识点", exact: true }).click();
  await page.getByLabel("知识点标题").fill("线性无关的判断");
  await page.getByLabel("简要说明").fill("判断向量组之间的线性关系");
  const original = "待修正结论：非零向量一定线性无关。";
  const corrected = "正确结论：零线性组合对应的系数只能全部为零，向量组才线性无关。";
  const markdown =
    "## 线性组合\n\n**定义**：系数与向量的组合。\n\n$$\n\\sum_{i=1}^{n} a_i v_i = 0\n$$\n\n| 符号 | 含义 |\n| --- | --- |\n| a | 系数 |";
  const formPreview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(formPreview, { recursive: true });
  await page.getByLabel("正文（Markdown）").fill(markdown);
  const previewRegion = page.getByRole("region", { name: "正文预览" });
  await expect(previewRegion.getByRole("heading", { name: "线性组合" })).toBeVisible();
  await expect(previewRegion.locator(".katex")).toBeVisible();
  await expect(previewRegion.getByRole("table")).toBeVisible();
  await page.screenshot({
    path: path.join(formPreview, "knowledge-create-preview.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "隐藏预览" }).click();
  await expect(previewRegion).toBeHidden();
  await expect(page.getByLabel("正文（Markdown）")).toHaveValue(markdown);
  await page.getByRole("button", { name: "显示预览" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(previewRegion.locator(".katex")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(formPreview, "knowledge-create-preview-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel("正文（Markdown）").fill(original);
  await page.getByRole("button", { name: "添加引用" }).click();
  await page.getByRole("button", { name: "读取原文" }).click();
  await expect(page.locator(".source-page-preview")).toContainText(
    "Only the trivial linear combination is zero.",
  );
  await page.getByLabel("引用文字").fill("Only the trivial linear combination is zero.");
  await page.getByRole("button", { name: "保存知识点" }).click();
  await expect(page.getByRole("heading", { name: "线性无关的判断", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "线性代数课件.pdf · 第 1 页" })).toBeVisible();
  const points = await (await page.request.get(base)).json();
  const pointId = points[0].id;

  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("正文（Markdown）").fill(corrected);
  await expect(page.getByRole("region", { name: "正文预览" })).toHaveText("预览" + corrected);
  await page.getByLabel("修改原因").fill("补充判断所需的必要条件");
  await page.getByRole("button", { name: "保存修订" }).click();
  await expect(page.locator(".knowledge-prose")).toHaveText(corrected);
  const oldHits = await page.request.post(base + "/search", { data: { query: "待修正结论" } });
  expect(await oldHits.json()).toEqual([]);
  const newHits = await page.request.post(base + "/search", { data: { query: "正确结论" } });
  expect((await newHits.json())[0].version).toBe(2);

  await page.getByRole("button", { name: "修订记录" }).click();
  await expect(page.getByText("补充判断所需的必要条件", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "恢复此版本" }).click();
  await page.getByRole("button", { name: "确认恢复" }).click();
  await page.getByRole("button", { name: "正文", exact: true }).click();
  await expect(page.locator(".knowledge-prose")).toHaveText(original);

  await page.getByRole("button", { name: "提出修改建议", exact: true }).click();
  await page.getByLabel("正文（Markdown）").fill(markdown);
  await expect(page.getByRole("region", { name: "正文预览" }).locator(".katex")).toBeVisible();
  await page.screenshot({
    path: path.join(formPreview, "knowledge-proposal-preview.png"),
    fullPage: true,
  });
  await page.getByLabel("正文（Markdown）").fill(corrected);
  await page.getByLabel("建议原因").fill("已与课件中的定义核对");
  await page.getByRole("button", { name: "提交建议" }).click();
  await expect(page.getByText("待确认", { exact: true })).toBeVisible();
  const unchanged = await (await page.request.get(base + `/${pointId}`)).json();
  expect(unchanged.content).toBe(original);
  await page.getByRole("button", { name: "交由模型处理", exact: true }).click();
  await expect(page.locator(".knowledge-comparison")).toContainText(original);
  await expect(page.locator(".knowledge-comparison")).toContainText(corrected);
  await page.getByRole("button", { name: "确认交由模型处理" }).click();
  await expect(page.getByRole("region", { name: "模型意见与处理结果" })).toContainText(
    "已写入第 4 版",
  );
  await expect(page.getByRole("region", { name: "模型意见与处理结果" })).toContainText(
    "测试审查：这条建议补充了必要条件，可以采纳。",
  );
  await page.getByRole("button", { name: "正文", exact: true }).click();
  await expect(page.locator(".knowledge-prose")).toHaveText(corrected);

  const preview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(preview, { recursive: true });
  await page.screenshot({ path: path.join(preview, "knowledge.png"), fullPage: true });
  await page.getByRole("button", { name: "归档", exact: true }).click();
  await page.getByRole("button", { name: "确认归档" }).click();
  await expect(page.getByRole("heading", { name: "暂无知识点" })).toBeVisible();
  await page.getByRole("button", { name: /^已归档/ }).click();
  await expect(page.getByRole("heading", { name: "线性无关的判断", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "修订记录" }).click();
  await page.getByRole("button", { name: "恢复此版本" }).first().click();
  await page.getByRole("button", { name: "确认恢复" }).click();
  await page.getByRole("button", { name: "正文", exact: true }).click();
  await expect(page.locator(".knowledge-prose")).toHaveText(corrected);

  await page.getByRole("textbox", { name: "搜索知识点" }).fill("不存在的词");
  await expect(page.getByRole("heading", { name: "没有找到相关知识点" })).toBeVisible();
  await page.getByRole("textbox", { name: "搜索知识点" }).fill("");
  await expect(page.getByRole("heading", { name: "线性无关的判断", exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "关闭导航" })).not.toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(preview, "knowledge-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  expect(errors).toEqual([]);
});

test("知识列表独立滚动，修改建议可删除", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `knowledge-scroll-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "知识列表滚动", color: "sage" } })
  ).json();
  const base = `/api/courses/${course.id}/knowledge`;
  const content = Array.from(
    { length: 40 },
    (_, index) => `第 ${index + 1} 段：正文保留在右侧，可以独立滚动阅读。`,
  ).join("\n\n");
  const points = [];
  for (let index = 1; index <= 26; index++) {
    const response = await page.request.post(base, {
      data: { title: `知识点 ${String(index).padStart(2, "0")}`, summary: "知识点摘要", content },
    });
    expect(response.status()).toBe(201);
    points.push(await response.json());
  }
  const proposalPath = `${base}/${points[0].id}/proposals`;
  expect(
    (
      await page.request.post(proposalPath, {
        data: {
          title: points[0].title,
          content: "建议修订的内容",
          expected_version: 1,
          reason: "这是一条可以删除的建议",
        },
      })
    ).status(),
  ).toBe(201);
  await page.goto(`/courses/${course.id}/knowledge`);
  const list = page.getByRole("complementary", { name: "知识点列表" });
  const detail = page.getByRole("region", { name: "知识点详情" });
  await expect(list.getByRole("button")).toHaveCount(26);
  expect(await list.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  expect(await detail.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(
    true,
  );
  const pageScroll = await page.evaluate(() => scrollY);
  const detailTop = (await detail.boundingBox())!.y;
  expect(
    await detail.evaluate((element) => element.getBoundingClientRect().bottom <= innerHeight),
  ).toBe(true);
  await list.hover();
  await page.mouse.wheel(0, 1300);
  await expect.poll(() => list.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  expect(await page.evaluate(() => scrollY)).toBe(pageScroll);
  expect((await detail.boundingBox())!.y).toBe(detailTop);
  await list.getByRole("button").last().click();
  await expect(detail.getByRole("heading", { name: "知识点 01", exact: true })).toBeVisible();
  expect(await detail.evaluate((element) => element.scrollTop)).toBe(0);
  await detail.hover();
  await page.mouse.wheel(0, 500);
  await expect.poll(() => detail.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  await list.hover();
  const rightScroll = await detail.evaluate((element) => element.scrollTop);
  await page.mouse.wheel(0, 300);
  await expect.poll(() => detail.evaluate((element) => element.scrollTop)).toBe(rightScroll);
  expect(await page.evaluate(() => scrollY)).toBe(pageScroll);
  const preview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(preview, { recursive: true });
  await page.screenshot({
    path: path.join(preview, "knowledge-independent-scroll.png"),
    fullPage: true,
  });
  await detail
    .locator(".knowledge-detail-tabs")
    .getByRole("button", { name: /^修改建议/ })
    .click();
  await expect(detail.getByText("这是一条可以删除的建议", { exact: true })).toBeVisible();
  expect(await detail.getByRole("button", { name: "拒绝", exact: true }).count()).toBe(0);
  await detail.getByRole("button", { name: "删除", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("知识正文和已有修订记录会保留");
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(detail.getByRole("heading", { name: "还没有修改建议" })).toBeVisible();
  expect(await (await page.request.get(proposalPath)).json()).toEqual([]);
  expect((await (await page.request.get(`${base}/${points[0].id}`)).json()).version).toBe(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await list.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
});
