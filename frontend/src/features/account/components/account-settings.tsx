"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Check, KeyRound, RefreshCw, Settings2 } from "lucide-react";
import { useAuth } from "@/features/auth/auth-provider";
import type { User } from "@/features/auth/types";
import { Modal, Notice, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/http";
import type { AccountModels, ModelConfig } from "../types";

function isLocalEndpoint(value: string) {
  return /^https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::|\/|$)/.test(value);
}

export default function AccountSettings() {
  const { user, mode, setUser } = useAuth();
  const personal = mode === "personal";
  useEffect(() => {
    document.title = `${personal ? "模型设置" : "账号设置"} | LearnFlow`;
  }, [personal]);
  const [data, setData] = useState<AccountModels | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState(user?.name || "");
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileMessage, setProfileMessage] = useState("");
  const [indexBusy, setIndexBusy] = useState(false);
  const [indexMessage, setIndexMessage] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);
  const [embeddingFormVersion, setEmbeddingFormVersion] = useState(0);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await api<AccountModels>("/account/models", { signal });
      if (!signal?.aborted) {
        setData(result);
        setError("");
      }
    } catch (err) {
      if (!signal?.aborted) setError(errorMessage(err));
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useEffect(() => {
    if (!data || (!data.rebuild && data.index.ready === data.index.total)) return;
    const controller = new AbortController();
    const timer = setInterval(() => void load(controller.signal), 5000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [load, !!data?.rebuild, data?.index.ready, data?.index.total]);
  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setProfileBusy(true);
    setProfileMessage("");
    try {
      const result = await api<User>("/account/profile", {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      setUser(result);
      setName(result.name);
      setProfileMessage("称呼已更新。");
    } catch (err) {
      setProfileMessage(errorMessage(err));
    } finally {
      setProfileBusy(false);
    }
  }
  async function indexAction(cancel = false) {
    setIndexBusy(true);
    setIndexMessage("");
    try {
      if (cancel) {
        setData(
          await api<AccountModels>(
            `/account/models/embedding/pending?expected_version=${data?.version}`,
            { method: "DELETE" },
          ),
        );
        setCancelOpen(false);
        setEmbeddingFormVersion((value) => value + 1);
        setIndexMessage("已取消切换，继续使用当前 Embedding。");
      } else {
        await api("/account/models/embedding/rebuild", { method: "POST" });
        setIndexMessage("索引任务已提交，后台会继续处理。");
        await load();
      }
    } catch (err) {
      setIndexMessage(errorMessage(err));
    } finally {
      setIndexBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          {!personal && <div className="eyebrow">个人账号</div>}
          <h1>{personal ? "模型设置" : "账号设置"}</h1>
          <p>
            {personal
              ? "模型设置对本机工作空间中的所有课程生效。"
              : "管理基本资料与模型连接，设置对账号下所有课程生效。"}
          </p>
        </div>
        <button className="button secondary" onClick={() => void load()}>
          刷新设置
        </button>
      </div>
      <div className="account-settings">
        {!personal && (
          <section className="settings-section" aria-label="基本资料">
            <div className="settings-section-heading">
              <Settings2 size={18} />
              <div>
                <h2>基本资料</h2>
                <p>邮箱用于登录，称呼会显示在工作空间中。</p>
              </div>
            </div>
            <form className="settings-fields" onSubmit={saveProfile}>
              <label>
                称呼
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={80}
                  required
                />
              </label>
              <label>
                邮箱
                <input value={user?.email || ""} disabled />
              </label>
              <div className="settings-actions">
                <button
                  className="button secondary"
                  disabled={profileBusy || !name.trim() || name.trim() === user?.name}
                >
                  {profileBusy ? "正在保存…" : "保存资料"}
                </button>
                {profileMessage && <p role="status">{profileMessage}</p>}
              </div>
            </form>
          </section>
        )}
        {error && <Notice message={error} retry={() => void load()} />}
        {!data && !error && <Spinner label="正在读取模型设置" />}
        {data && (
          <>
            <ModelForm kind="llm" initial={data.llm} version={data.version} onSaved={setData} />
            <ModelForm
              key={embeddingFormVersion}
              kind="embedding"
              initial={data.pending_embedding || data.embedding}
              version={data.version}
              onSaved={setData}
            />
            <section
              className="settings-section"
              aria-label={personal ? "本地知识索引" : "账号知识索引"}
            >
              <div className="settings-section-heading">
                <RefreshCw size={18} />
                <div>
                  <h2>知识索引</h2>
                  <p>
                    {personal
                      ? "所有课程共用本机的 Embedding 设置，各课程的知识仍分别检索。"
                      : "所有课程共用账号的 Embedding，各课程的知识仍分别检索。"}
                  </p>
                </div>
              </div>
              <div className="settings-index-content">
                <p>
                  当前模型：<strong>{data.embedding.model || "未配置"}</strong>
                  {data.embedding.dimensions ? ` · ${data.embedding.dimensions} 维` : ""}
                </p>
                <p>
                  当前索引：{data.index.ready} / {data.index.total} 个知识块就绪
                  {data.index.failed > 0 ? `，${data.index.failed} 个失败` : ""}
                </p>
                {data.pending_embedding && data.rebuild && (
                  <div className="settings-rebuild" role="status">
                    <strong>正在切换至 {data.pending_embedding.model}</strong>
                    <p>
                      新索引 {data.rebuild.ready} / {data.rebuild.total}，失败 {data.rebuild.failed}
                      。全部完成后自动切换，期间继续使用当前模型。
                    </p>
                    <progress
                      value={data.rebuild.ready}
                      max={Math.max(1, data.rebuild.total)}
                      aria-label="新索引进度"
                    />
                  </div>
                )}
                <div className="settings-actions">
                  <button
                    className="button secondary"
                    onClick={() => void indexAction()}
                    disabled={indexBusy || (!data.rebuild && data.index.ready === data.index.total)}
                  >
                    {indexBusy ? "正在提交…" : "补建 / 重试索引"}
                  </button>
                  {data.pending_embedding && (
                    <button
                      className="text-button"
                      disabled={indexBusy}
                      onClick={() => setCancelOpen(true)}
                    >
                      取消本次模型切换
                    </button>
                  )}
                </div>
                {indexMessage && (
                  <p className="settings-feedback" role="status">
                    {indexMessage}
                  </p>
                )}
              </div>
            </section>
          </>
        )}
      </div>
      {cancelOpen && (
        <Modal
          title="取消这次模型切换？"
          description="当前模型与现有索引会保留，尚未启用的新索引会被清理。"
          busy={indexBusy}
          onClose={() => setCancelOpen(false)}
        >
          {indexMessage && <Notice message={indexMessage} />}
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={indexBusy}
              onClick={() => setCancelOpen(false)}
            >
              继续重建
            </button>
            <button
              className="button danger"
              disabled={indexBusy}
              onClick={() => void indexAction(true)}
            >
              确认取消切换
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function ModelForm({
  kind,
  initial,
  version,
  onSaved,
}: {
  kind: "llm" | "embedding";
  initial: ModelConfig;
  version: number;
  onSaved: (value: AccountModels) => void;
}) {
  const personal = useAuth().mode === "personal";
  const title = kind === "llm" ? "LLM" : "Embedding";
  const [form, setForm] = useState(initial);
  const [key, setKey] = useState("");
  const [noKey, setNoKey] = useState(isLocalEndpoint(initial.base_url) && !initial.has_api_key);
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [feedback, setFeedback] = useState("");
  const [failed, setFailed] = useState(false);
  function update(values: Partial<ModelConfig>) {
    setForm((old) => ({ ...old, ...values }));
    setFeedback("");
  }
  function changeProvider(provider: ModelConfig["provider"]) {
    setKey("");
    setNoKey(false);
    if (provider === "siliconflow") {
      update({
        provider,
        base_url: "https://api.siliconflow.cn/v1",
        model: kind === "llm" ? "deepseek-ai/DeepSeek-V4-Flash" : "Qwen/Qwen3-Embedding-8B",
        vision: false,
        structured_output: "json_object",
        enable_thinking: false,
        dimensions: 1024,
        send_dimensions: true,
        revision: "",
      });
    } else if (provider === "deepseek") {
      update({
        provider,
        base_url: "https://api.deepseek.com",
        model: "deepseek-flash",
        vision: true,
        structured_output: "json_object",
        enable_thinking: true,
      });
    } else if (provider === "aliyun") {
      update({
        provider,
        base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: kind === "llm" ? "qwen3.8-flash" : "qwen3.7-text-embedding",
        vision: true,
        structured_output: "json_schema",
        enable_thinking: false,
      });
    } else {
      update({ provider });
    }
  }
  function changeModel(model: string) {
    const fixedEmbedding = ["BAAI/bge-m3", "Pro/BAAI/bge-m3", "BAAI/bge-large-zh-v1.5"];
    update({
      model,
      ...(kind === "embedding" && form.provider === "siliconflow"
        ? fixedEmbedding.includes(model)
          ? { dimensions: 1024, send_dimensions: false }
          : model.startsWith("Qwen/Qwen3-Embedding-")
            ? { dimensions: 1024, send_dimensions: true }
            : {}
        : {}),
    });
  }
  async function action(type: "save" | "test") {
    setBusy(type);
    setFeedback("");
    setFailed(false);
    const body = { ...form, expected_version: version, api_key: noKey ? "" : key.trim() || null };
    try {
      if (type === "test") {
        const result = await api<{ message: string }>(`/account/models/${kind}/test`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        setFeedback(result.message);
      } else {
        const result = await api<AccountModels>(`/account/models/${kind}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
        onSaved(result);
        setKey("");
        setForm(kind === "llm" ? result.llm : result.pending_embedding || result.embedding);
        setFeedback(
          kind === "llm"
            ? `LLM 已保存，对${personal ? "本机" : "账号下"}所有课程生效。`
            : result.queued === false
              ? "设置已保存，索引暂未入队，可在下方重试。"
              : result.pending_embedding
                ? "设置已保存。新索引全部完成后自动切换。"
                : "Embedding 已保存。",
        );
      }
    } catch (err) {
      setFeedback(errorMessage(err));
      setFailed(true);
    } finally {
      setBusy(null);
    }
  }
  return (
    <section className="settings-section" aria-label={`${title} 设置`}>
      <div className="settings-section-heading">
        <KeyRound size={18} />
        <div>
          <h2>{title}</h2>
          <p>
            {kind === "llm"
              ? "用于问答、修改建议处理与课件识别。课件识别需要模型支持图片。"
              : "将知识文本和问题转换为向量，供本地知识库检索。"}
          </p>
        </div>
        <span className="settings-source">
          {initial.source === "system"
            ? "当前使用系统默认"
            : personal
              ? "本机自定义"
              : "账号自定义"}
        </span>
      </div>
      <form
        className="settings-fields"
        onSubmit={(event) => {
          event.preventDefault();
          void action("save");
        }}
      >
        <label>
          接口类型
          <select
            aria-label={`${title} 接口类型`}
            value={form.provider}
            onChange={(e) => changeProvider(e.target.value as ModelConfig["provider"])}
          >
            <option value="aliyun">阿里云百炼</option>
            <option value="siliconflow">硅基流动 SiliconFlow</option>
            {kind === "llm" && <option value="deepseek">DeepSeek</option>}
            <option value="openai_compatible">OpenAI 兼容接口</option>
          </select>
        </label>
        <label>
          模型名称
          {form.provider === "deepseek" ? (
            <select
              aria-label={`${title} 模型名称`}
              value={form.model}
              onChange={(e) =>
                update({ model: e.target.value, vision: e.target.value === "deepseek-flash" })
              }
            >
              <option value="deepseek-flash">deepseek-flash（支持图片）</option>
              <option value="deepseek-v4-pro">deepseek-v4-pro（仅文本）</option>
            </select>
          ) : (
            <input
              aria-label={`${title} 模型名称`}
              value={form.model}
              onChange={(e) => changeModel(e.target.value)}
              list={
                form.provider === "siliconflow" && kind === "embedding"
                  ? "siliconflow-embedding-models"
                  : undefined
              }
              maxLength={128}
              required
              placeholder={
                form.provider === "siliconflow"
                  ? kind === "llm"
                    ? "deepseek-ai/DeepSeek-V4-Flash"
                    : "Qwen/Qwen3-Embedding-8B"
                  : kind === "llm"
                    ? "qwen3.8-flash"
                    : "qwen3.7-text-embedding"
              }
            />
          )}
          {form.provider === "siliconflow" && kind === "embedding" && (
            <datalist id="siliconflow-embedding-models">
              <option value="Qwen/Qwen3-Embedding-8B" />
              <option value="Qwen/Qwen3-Embedding-4B" />
              <option value="Qwen/Qwen3-Embedding-0.6B" />
              <option value="BAAI/bge-m3" />
              <option value="Pro/BAAI/bge-m3" />
              <option value="BAAI/bge-large-zh-v1.5" />
            </datalist>
          )}
          {form.provider === "siliconflow" && (
            <span className="settings-help">填写控制台的完整模型名称，保留组织名前缀。</span>
          )}
        </label>
        <label className="settings-full">
          API 地址
          <input
            aria-label={`${title} API 地址`}
            value={form.base_url}
            onChange={(e) => update({ base_url: e.target.value })}
            required
            maxLength={500}
            placeholder="https://example.com/v1"
            spellCheck={false}
          />
          <span className="settings-help">
            填写接口基础地址，不包含 /chat/completions 或 /embeddings。
          </span>
        </label>
        <label className="settings-full">
          API Key
          <input
            aria-label={`${title} API Key`}
            type="password"
            autoComplete="new-password"
            value={key}
            disabled={noKey}
            onChange={(e) => {
              setKey(e.target.value);
              setFeedback("");
            }}
            maxLength={4096}
            placeholder={
              initial.has_api_key &&
              form.provider === initial.provider &&
              form.base_url === initial.base_url
                ? "已保存，留空保留原密钥"
                : "填写 API Key"
            }
          />
          <span className="settings-help">
            密钥加密保存，仅本人可使用。更换服务商或 API 地址后需重新填写。
          </span>
        </label>
        {isLocalEndpoint(form.base_url) && (
          <label className="settings-check settings-full">
            <input type="checkbox" checked={noKey} onChange={(e) => setNoKey(e.target.checked)} />
            本机接口无需 API Key
          </label>
        )}
        {kind === "llm" ? (
          <>
            <label>
              结构化输出
              <select
                aria-label="LLM 结构化输出"
                value={form.structured_output || "json_schema"}
                disabled={form.provider === "deepseek"}
                onChange={(e) =>
                  update({ structured_output: e.target.value as ModelConfig["structured_output"] })
                }
              >
                <option value="json_schema">JSON Schema</option>
                <option value="json_object">JSON Object</option>
              </select>
            </label>
            <label className="settings-check">
              <input
                type="checkbox"
                checked={form.vision ?? true}
                disabled={form.provider === "deepseek" && form.model === "deepseek-v4-pro"}
                onChange={(e) => update({ vision: e.target.checked })}
              />
              模型支持图片识别
            </label>
            {["deepseek", "aliyun", "siliconflow"].includes(form.provider) && (
              <label className="settings-check settings-full">
                <input
                  type="checkbox"
                  checked={form.enable_thinking ?? false}
                  onChange={(e) => update({ enable_thinking: e.target.checked })}
                />
                启用思考模式
                <span className="settings-help">思考会占用输出额度，响应时间可能增加。</span>
              </label>
            )}
            {form.provider === "deepseek" && form.model === "deepseek-v4-pro" && (
              <p className="settings-help settings-full">
                Pro 可用于文字问答和修改建议，无法识别课件页面或聊天图片；需要图片时请选择 Flash。
              </p>
            )}
            {form.provider === "siliconflow" && (
              <p className="settings-help settings-full">
                课件和聊天图片识别需要使用支持视觉的模型，并勾选“模型支持图片识别”；结构化输出和思考模式需与所选模型能力一致。
              </p>
            )}
          </>
        ) : (
          <>
            <label>
              向量维度
              <input
                aria-label="Embedding 向量维度"
                type="number"
                min={1}
                max={16000}
                value={form.dimensions ?? 1024}
                onChange={(e) => update({ dimensions: Number(e.target.value) })}
                required
              />
            </label>
            <label>
              模型版本（可选）
              <input
                aria-label="Embedding 模型版本"
                value={form.revision || ""}
                onChange={(e) => update({ revision: e.target.value })}
                maxLength={100}
                placeholder="服务商提供的版本号"
              />
            </label>
            <label className="settings-check settings-full">
              <input
                type="checkbox"
                checked={form.send_dimensions ?? true}
                onChange={(e) => update({ send_dimensions: e.target.checked })}
              />
              请求中发送 dimensions 参数
              <span className="settings-help">
                {form.provider === "siliconflow"
                  ? "硅基流动的 Qwen3 嵌入模型支持此参数；BGE 等固定维度模型请取消勾选。"
                  : "固定维度且不接受此参数的接口，请取消勾选。"}
              </span>
            </label>
          </>
        )}
        <p className="settings-model-note settings-full">
          {kind === "embedding"
            ? `保存新的模型、地址、版本或维度会重建${personal ? "本机" : "账号下"}所有课程的向量。知识文本会发送到所填写的服务，可能产生调用费用；仅更换密钥无需重建。`
            : "提问及课件识别时，相关文本或页面图片会发送到所填写的服务。测试连接仅发送固定样本，可能产生调用费用。"}
        </p>
        <div className="settings-actions settings-full">
          <button
            type="button"
            className="button secondary"
            disabled={!!busy || !form.model || !form.base_url}
            onClick={() => void action("test")}
          >
            {busy === "test" ? "正在测试…" : "测试连接"}
          </button>
          <button className="button primary" disabled={!!busy}>
            {busy === "save" ? "正在保存…" : kind === "embedding" ? "保存并更新索引" : "保存 LLM"}
          </button>
        </div>
        {feedback && (
          <p
            className={`settings-feedback settings-full ${failed ? "is-error" : ""}`}
            role={failed ? "alert" : "status"}
          >
            {!failed && <Check size={14} />}
            {feedback}
          </p>
        )}
      </form>
    </section>
  );
}
