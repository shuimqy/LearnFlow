import { expect, test } from "@playwright/test";

function samplePdf() {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << >> >>",
  ];
  let content = "%PDF-1.4\n";
  const offsets = objects.map((object, index) => {
    const offset = Buffer.byteLength(content);
    content += `${index + 1} 0 obj\n${object}\nendobj\n`;
    return offset;
  });
  const xref = Buffer.byteLength(content);
  content += `xref\n0 4\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(content);
}

test("免登录进入、课件与知识、模型配置保存、重开浏览器和登录页跳转", async ({ page, browser }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /^我的课程/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "模型设置", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "退出登录" })).toHaveCount(0);
  expect(
    (await page.context().cookies()).some((cookie) => cookie.name === "learnflow_session"),
  ).toBe(false);
  const identity = await (await page.request.get("/api/auth/me")).json();
  expect(identity.mode).toBe("personal");
  const name = `单机测试-${Date.now()}`;
  const course = await (
    await page.request.post("/api/courses", { data: { name, color: "sage" } })
  ).json();
  try {
    const upload = await page.request.post(`/api/courses/${course.id}/documents`, {
      multipart: {
        file: { name: "单机课件.pdf", mimeType: "application/pdf", buffer: samplePdf() },
      },
    });
    expect(upload.status()).toBe(201);
    const document = await upload.json();
    expect((await page.request.get(`/api/documents/${document.id}/file`)).status()).toBe(200);
    const point = await page.request.post(`/api/courses/${course.id}/knowledge`, {
      data: {
        title: "单机知识点",
        content: "向量组线性无关的判断条件。",
        sources: [{ document_id: document.id, page_number: 1 }],
      },
    });
    expect(point.status()).toBe(201);
    await page.reload();
    await expect(page.getByRole("link", { name, exact: true }).first()).toBeVisible();
    await page.goto(`/courses/${course.id}/knowledge`);
    await expect(page.getByRole("button", { name: /单机知识点/ })).toBeVisible();
    await page.goto(`/courses/${course.id}/chat`);
    await page.getByRole("textbox", { name: "向课程助手提问" }).fill("线性无关的判断条件是什么？");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect(page.locator(".chat-message.assistant .katex-display")).toBeVisible();
    await page.getByRole("link", { name: "模型设置", exact: true }).click();
    await expect(page.getByRole("heading", { name: "模型设置", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "基本资料" })).toHaveCount(0);
    const llm = page.getByRole("region", { name: "LLM 设置" });
    await llm.getByLabel("LLM 接口类型").selectOption("siliconflow");
    await llm.getByLabel("LLM API Key", { exact: true }).fill("sk-personal-browser-fixture");
    await llm.getByRole("button", { name: "测试连接", exact: true }).click();
    await expect(llm.getByRole("status")).toContainText("结构化输出校验通过");
    await llm.getByRole("button", { name: "保存 LLM", exact: true }).click();
    await expect(llm.getByRole("status")).toContainText("LLM 已保存");
    const separate = await browser.newContext({ baseURL: "http://127.0.0.1:3100" });
    try {
      const fresh = await separate.newPage();
      await fresh.goto("/login");
      await expect(fresh).toHaveURL("http://127.0.0.1:3100/");
      await expect(fresh.getByRole("link", { name, exact: true }).first()).toBeVisible();
      expect((await (await fresh.request.get("/api/auth/me")).json()).id).toBe(identity.id);
      await fresh.getByRole("link", { name: "模型设置", exact: true }).click();
      await expect(fresh.getByLabel("LLM 接口类型")).toHaveValue("siliconflow");
      await expect(fresh.getByLabel("LLM API Key", { exact: true })).toHaveValue("");
    } finally {
      await separate.close();
    }
    expect(errors).toEqual([]);
  } finally {
    await page.request.delete(`/api/courses/${course.id}`);
  }
});
