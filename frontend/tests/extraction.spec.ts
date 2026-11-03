import { expect, test } from "@playwright/test";

test("识别自动入库，完成后直接打开知识库", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `extraction-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", {
      data: { name: "线性代数", color: "sage", description: "公式与例题" },
    })
  ).json();
  const pdf = Buffer.from(
    "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<<>>>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF",
  );
  const uploaded = await page.request.post(`/api/courses/${course.id}/documents`, {
    multipart: { file: { name: "公式与例题.pdf", mimeType: "application/pdf", buffer: pdf } },
  });
  expect(uploaded.status()).toBe(201);
  const document = await uploaded.json();
  let complete = false;
  await page.route(`**/api/documents/${document.id}/extraction`, async (route) => {
    await route.fulfill({
      json: {
        document_id: document.id,
        page_count: 1,
        task: {
          ...document.task,
          status: complete ? "completed" : "running",
          stage: complete ? "imported" : "extracting",
          progress: complete ? 100 : 50,
        },
        pages: [
          {
            id: "page",
            page_number: 1,
            status: complete ? "completed" : "running",
            warnings: [],
            error: null,
            counts: complete ? { imported: 2 } : {},
          },
        ],
      },
    });
  });
  await page.route(`**/api/courses/${course.id}/documents`, async (route) => {
    await route.fulfill({
      json: [
        {
          ...document,
          task: { ...document.task, status: "completed", stage: "imported", progress: 100 },
        },
      ],
    });
  });
  await page.goto(`/courses/${course.id}/documents/${document.id}/extraction`);
  await expect(page.getByRole("heading", { name: "课件处理进度" })).toBeVisible();
  await expect(page.getByText("正在识别并存入知识库 · 50%", { exact: true })).toBeVisible();
  expect(await page.getByRole("checkbox").count()).toBe(0);
  expect(await page.getByRole("button", { name: "确认并存入知识库" }).count()).toBe(0);
  for (const [title, content] of [
    ["分式与幂", "分母不能为零。\n\n$$\n\\frac{x^2}{y_1}\n$$"],
    [
      "例题：计算分式",
      "## 题干\n\n计算 $\\frac{4}{2}$。\n\n## 课件答案\n\n2\n\n## 课件解题步骤\n\n课件未提供解题步骤。",
    ],
  ]) {
    const response = await page.request.post(`/api/courses/${course.id}/knowledge`, {
      data: {
        title,
        summary: "",
        content,
        sources: [{ document_id: document.id, page_number: 1 }],
      },
    });
    expect(response.status()).toBe(201);
  }
  complete = true;
  await expect(page).toHaveURL(`/courses/${course.id}/knowledge`, { timeout: 10000 });
  await expect(page.getByRole("heading", { name: "课程知识库", level: 1 })).toBeVisible();
  await expect(page.locator(".knowledge-prose .katex")).toBeVisible();
  await expect(page.getByRole("link", { name: "公式与例题.pdf · 第 1 页" })).toBeVisible();
  await page.goto(`/courses/${course.id}`);
  const knowledgeLink = page.getByRole("link", { name: "查看知识库", exact: true });
  await expect(knowledgeLink).toHaveAttribute("href", `/courses/${course.id}/knowledge`);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto(`/courses/${course.id}/documents/${document.id}/extraction`);
  await expect(page).toHaveURL(`/courses/${course.id}/knowledge`);
  expect(errors).toEqual([]);
});
