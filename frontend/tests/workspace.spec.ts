import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const preview = path.resolve(__dirname, "../../.local/previews");
const password = "course-notes-2026";

function samplePdf() {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << >> >>",
  ];
  let data = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(data));
    data += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = Buffer.byteLength(data);
  data += `xref\n0 4\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`)
    .join("")}trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(data);
}

test("注册、课程管理、上传及删除形成完整流程", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  mkdirSync(preview, { recursive: true });
  const email = `browser-${Date.now()}@example.com`;
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
  await page.screenshot({ path: path.join(preview, "login.png"), fullPage: true });
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  await page.getByLabel("称呼").fill("小林");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  await expect(page.getByRole("heading", { name: "我的课程" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "暂无课程" })).toBeVisible();
  await page.screenshot({ path: path.join(preview, "empty-library.png"), fullPage: true });

  await page.getByRole("button", { name: "创建课程", exact: true }).click();
  await page.getByLabel("课程名称").fill("线性代数");
  await page.getByLabel("课程简介").fill("向量、矩阵与线性变换");
  await page.getByRole("dialog").getByRole("button", { name: "创建课程", exact: true }).click();
  await expect(page.getByRole("heading", { name: "线性代数" })).toBeVisible();
  for (const [name, description, color] of [
    ["概率论与数理统计", "从随机变量到统计推断", "blue"],
    ["数据结构", "理解算法，也理解数据", "sand"],
  ]) {
    const response = await page.request.post("/api/courses", {
      data: { name, description, color },
    });
    expect(response.status()).toBe(201);
  }
  await page.reload();
  await expect(page.getByRole("heading", { name: "线性代数" })).toBeVisible();
  await page.screenshot({ path: path.join(preview, "course-library.png"), fullPage: true });
  await page.getByRole("link", { name: /线性代数.*向量/ }).click();
  await expect(page.getByRole("heading", { name: "线性代数", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "上传课件", exact: true }).click();
  await page
    .getByLabel("选择 PDF 文件")
    .setInputFiles({ name: "第一章-向量.pdf", mimeType: "application/pdf", buffer: samplePdf() });
  await page.getByText("提取原题", { exact: true }).click();
  await page.getByRole("button", { name: "上传课件", exact: true }).last().click();
  await expect(page.getByRole("link", { name: "第一章-向量.pdf" })).toBeVisible();
  await expect(page.getByRole("link", { name: "提取知识与例题" })).toBeVisible();
  for (const name of ["课程问答", "课程知识库"]) {
    const action = page.getByRole("link", { name, exact: true });
    await expect(action).toBeInViewport();
    expect((await action.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
  const deleteCourse = page.getByRole("button", { name: "删除课程", exact: true });
  await expect(deleteCourse).toBeVisible();
  expect((await deleteCourse.boundingBox())!.height).toBeGreaterThanOrEqual(39);
  await page.screenshot({ path: path.join(preview, "course-detail.png"), fullPage: true });
  const fileLink = page.getByRole("link", { name: "第一章-向量.pdf" });
  const source = await page.request.get((await fileLink.getAttribute("href"))!);
  expect(source.headers()["content-type"]).toContain("application/pdf");
  expect(source.status()).toBe(200);

  await page.getByRole("button", { name: "课程设置" }).click();
  await page.getByLabel("课程名称").fill("线性代数 · 秋季");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.getByRole("heading", { name: "线性代数 · 秋季", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "处理记录" }).click();
  await expect(page.getByRole("link", { name: "第一章-向量.pdf" })).toBeVisible();
  await expect(page.getByText("等待处理", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "第一章-向量.pdf" }).click();
  await page.getByRole("button", { name: "删除 第一章-向量.pdf" }).click();
  await page.getByRole("button", { name: "确认删除" }).click();
  await expect(page.getByRole("heading", { name: "暂无课件" })).toBeVisible();
  await page.getByRole("button", { name: "删除课程", exact: true }).click();
  await page.getByRole("button", { name: "确认删除" }).click();
  await expect(page.getByRole("heading", { name: "我的课程" })).toBeVisible();

  await page.getByRole("button", { name: "列表视图" }).click();
  await page.getByRole("textbox", { name: "搜索课程" }).fill("不存在的课程");
  await expect(page.getByRole("heading", { name: "没有找到相关课程" })).toBeVisible();
  await page.getByRole("button", { name: "清空搜索" }).click();
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "我的课程" })).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test("手机布局和导航可用", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.request.post("/api/auth/register", {
    data: {
      email: `mobile-${Date.now()}@example.com`,
      password,
      name: "小周",
    },
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "我的课程" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: path.join(preview, "mobile-library.png"), fullPage: true });
  await page.getByRole("button", { name: "打开导航" }).click();
  await page.getByRole("link", { name: "处理记录" }).click();
  await expect(page.getByRole("heading", { name: "处理记录", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "还没有处理记录" })).toBeVisible();
  await page.goto("/");
  await page.getByRole("button", { name: "创建课程", exact: true }).click();
  await page.getByLabel("课程名称").fill("离散数学");
  await page.getByRole("dialog").getByRole("button", { name: "创建课程", exact: true }).click();
  await expect(page.getByRole("heading", { name: "离散数学" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
