import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

test("硅基流动 LLM、Embedding 预设与固定维度参数保存", async ({ page }) => {
  await page.request.post("/api/auth/register", {
    data: {
      name: "硅基流动测试",
      email: `siliconflow-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  await page.goto("/settings");
  const llm = page.getByRole("region", { name: "LLM 设置" });
  await llm.getByLabel("LLM 接口类型").selectOption("siliconflow");
  await expect(llm.getByLabel("LLM API 地址")).toHaveValue("https://api.siliconflow.cn/v1");
  await expect(llm.getByLabel("LLM 模型名称")).toHaveValue("deepseek-ai/DeepSeek-V4-Flash");
  await expect(llm.getByLabel("LLM 结构化输出")).toHaveValue("json_object");
  await expect(llm.getByLabel("启用思考模式")).not.toBeChecked();
  await expect(llm.getByLabel("模型支持图片识别")).not.toBeChecked();
  await expect(llm.getByLabel("LLM API Key", { exact: true })).toHaveAttribute(
    "placeholder",
    "填写 API Key",
  );
  await llm.getByLabel("LLM API Key", { exact: true }).fill("sk-siliconflow-browser-fixture");
  await llm.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(llm.getByRole("status")).toContainText("结构化输出校验通过");
  await llm.getByRole("button", { name: "保存 LLM", exact: true }).click();
  await expect(llm.getByRole("status")).toContainText("LLM 已保存");
  const embedding = page.getByRole("region", { name: "Embedding 设置" });
  await embedding.getByLabel("Embedding 接口类型").selectOption("siliconflow");
  await expect(embedding.getByLabel("Embedding API 地址")).toHaveValue(
    "https://api.siliconflow.cn/v1",
  );
  await expect(embedding.getByLabel("Embedding 模型名称")).toHaveValue("Qwen/Qwen3-Embedding-8B");
  await expect(embedding.getByLabel("Embedding 向量维度")).toHaveValue("1024");
  await expect(embedding.getByLabel("请求中发送 dimensions 参数")).toBeChecked();
  await embedding.getByLabel("Embedding 模型名称").fill("BAAI/bge-m3");
  await expect(embedding.getByLabel("请求中发送 dimensions 参数")).not.toBeChecked();
  await embedding.getByLabel("Embedding 模型名称").fill("Qwen/Qwen3-Embedding-0.6B");
  await expect(embedding.getByLabel("请求中发送 dimensions 参数")).toBeChecked();
  await embedding.getByLabel("Embedding 模型名称").fill("BAAI/bge-m3");
  await embedding
    .getByLabel("Embedding API Key", { exact: true })
    .fill("sk-siliconflow-browser-fixture");
  await embedding.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(embedding.getByRole("status")).toContainText("返回维度符合设置");
  await embedding.getByRole("button", { name: "保存并更新索引", exact: true }).click();
  await expect(embedding.getByRole("status")).toContainText("Embedding 已保存");
  await page.reload();
  await expect(llm.getByLabel("LLM 接口类型")).toHaveValue("siliconflow");
  await expect(embedding.getByLabel("Embedding 接口类型")).toHaveValue("siliconflow");
  await expect(embedding.getByLabel("Embedding 模型名称")).toHaveValue("BAAI/bge-m3");
  await expect(embedding.getByLabel("请求中发送 dimensions 参数")).not.toBeChecked();
  const state = await (await page.request.get("/api/account/models")).json();
  expect(JSON.stringify(state)).not.toContain("sk-siliconflow");
  const preview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(preview, { recursive: true });
  await page.screenshot({ path: path.join(preview, "siliconflow-settings.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("DeepSeek 预设、思考开关和 Pro 图片限制", async ({ page }) => {
  await page.request.post("/api/auth/register", {
    data: {
      name: "DeepSeek 测试",
      email: `deepseek-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  await page.goto("/settings");
  const llm = page.getByRole("region", { name: "LLM 设置" });
  await llm.getByLabel("LLM 接口类型").selectOption("deepseek");
  await expect(llm.getByLabel("LLM API 地址")).toHaveValue("https://api.deepseek.com");
  await expect(llm.getByLabel("LLM 模型名称")).toHaveValue("deepseek-flash");
  await expect(llm.getByLabel("启用思考模式")).toBeChecked();
  await expect(llm.getByLabel("模型支持图片识别")).toBeChecked();
  await expect(llm.getByLabel("LLM 结构化输出")).toHaveValue("json_object");
  await expect(llm.getByLabel("LLM 结构化输出")).toBeDisabled();
  await llm.getByLabel("LLM 模型名称").selectOption("deepseek-v4-pro");
  await expect(llm.getByLabel("模型支持图片识别")).not.toBeChecked();
  await expect(llm.getByLabel("模型支持图片识别")).toBeDisabled();
  await expect(llm.getByText(/Pro 可用于文字问答/)).toBeVisible();
  await llm.getByLabel("启用思考模式").uncheck();
  await llm.getByLabel("LLM API Key", { exact: true }).fill("sk-browser-deepseek-private-key");
  await llm.getByRole("button", { name: "保存 LLM" }).click();
  await expect(llm.getByRole("status")).toContainText("LLM 已保存");
  await page.reload();
  await expect(llm.getByLabel("LLM 模型名称")).toHaveValue("deepseek-v4-pro");
  await expect(llm.getByLabel("启用思考模式")).not.toBeChecked();
  await llm.getByLabel("LLM 模型名称").selectOption("deepseek-flash");
  await expect(llm.getByLabel("模型支持图片识别")).toBeChecked();
  await llm.getByRole("button", { name: "保存 LLM" }).click();
  await expect(llm.getByRole("status")).toContainText("LLM 已保存");
  const state = await (await page.request.get("/api/account/models")).json();
  expect(state.llm.model).toBe("deepseek-flash");
  expect(state.llm.has_api_key).toBe(true);
  expect(state.llm.vision).toBe(true);
  expect(JSON.stringify(state)).not.toContain("sk-browser");
  const embedding = page.getByRole("region", { name: "Embedding 设置" });
  await expect(embedding.getByRole("option", { name: "DeepSeek", exact: true })).toHaveCount(0);
});

test("账号资料、模型测试、密钥保留与索引切换设置", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.request.post("/api/auth/register", {
    data: {
      name: "小林",
      email: `settings-${Date.now()}@example.com`,
      password: "course-notes-2026",
    },
  });
  const course = await (
    await page.request.post("/api/courses", { data: { name: "线性代数", color: "sage" } })
  ).json();
  await page.request.post(`/api/courses/${course.id}/knowledge`, {
    data: { title: "线性无关", content: "零线性组合只有全零系数。" },
  });
  await page.goto("/");
  await page.getByRole("link", { name: "账号设置", exact: true }).click();
  await expect(page.getByRole("heading", { name: "账号设置", level: 1 })).toBeVisible();
  await page.getByLabel("称呼", { exact: true }).fill("阿林");
  await page.getByRole("button", { name: "保存资料" }).click();
  await expect(page.getByText("称呼已更新。", { exact: true })).toBeVisible();
  expect((await (await page.request.get("/api/auth/me")).json()).name).toBe("阿林");
  const llm = page.getByRole("region", { name: "LLM 设置" });
  await llm.getByLabel("LLM 接口类型").selectOption("openai_compatible");
  await llm.getByLabel("LLM API 地址").fill("https://models.example.com/v1");
  await llm.getByLabel("LLM API Key", { exact: true }).fill("sk-browser-llm-private-key");
  await llm.getByLabel("模型支持图片识别").uncheck();
  await llm.getByLabel("LLM 模型名称").fill("unavailable-model");
  await llm.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(llm.getByRole("alert")).toContainText("测试未通过");
  await llm.getByLabel("LLM 模型名称").fill("custom-chat");
  await llm.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(llm.getByRole("status")).toContainText("结构化输出校验通过");
  await llm.getByRole("button", { name: "保存 LLM" }).click();
  await expect(llm.getByRole("status")).toContainText("对账号下所有课程生效");
  await expect(llm.getByLabel("LLM API Key", { exact: true })).toHaveValue("");
  await page.reload();
  await expect(llm.getByLabel("LLM 模型名称")).toHaveValue("custom-chat");
  await expect(llm.getByLabel("LLM API Key", { exact: true })).toHaveAttribute(
    "placeholder",
    "已保存，留空保留原密钥",
  );
  await llm.getByLabel("LLM 模型名称").fill("custom-chat-2");
  await llm.getByRole("button", { name: "保存 LLM" }).click();
  await expect(llm.getByRole("status")).toContainText("LLM 已保存");
  const embedding = page.getByRole("region", { name: "Embedding 设置" });
  await embedding.getByLabel("Embedding 接口类型").selectOption("openai_compatible");
  await embedding.getByLabel("Embedding API 地址").fill("https://vectors.example.com/v1");
  await embedding.getByLabel("Embedding 模型名称").fill("custom-embedding");
  await embedding
    .getByLabel("Embedding API Key", { exact: true })
    .fill("sk-browser-embedding-private-key");
  await embedding.getByLabel("Embedding 向量维度").fill("2");
  await embedding.getByLabel("请求中发送 dimensions 参数").uncheck();
  await embedding.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(embedding.getByRole("status")).toContainText("返回维度符合设置");
  await embedding.getByRole("button", { name: "保存并更新索引" }).click();
  await expect(embedding.getByRole("status")).toContainText("新索引全部完成后自动切换");
  const index = page.getByRole("region", { name: "账号知识索引" });
  await expect(index).toContainText("正在切换至 custom-embedding");
  await expect(index).toContainText("新索引 0 / 1");
  const state = await (await page.request.get("/api/account/models")).json();
  expect(JSON.stringify(state)).not.toContain("sk-browser");
  expect(state.llm.model).toBe("custom-chat-2");
  expect(state.pending_embedding.model).toBe("custom-embedding");
  const preview = path.resolve(__dirname, "../../.local/previews");
  mkdirSync(preview, { recursive: true });
  await page.screenshot({ path: path.join(preview, "account-settings.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "关闭导航" })).not.toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(preview, "account-settings-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  await index.getByRole("button", { name: "取消本次模型切换" }).click();
  await page.getByRole("button", { name: "确认取消切换" }).click();
  await expect(index).not.toContainText("正在切换至");
  await expect(embedding.getByLabel("Embedding 模型名称")).toHaveValue(state.embedding.model);
  expect(errors).toEqual([]);
});
