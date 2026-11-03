export type ModelConfig = {
  provider: "aliyun" | "deepseek" | "siliconflow" | "openai_compatible";
  base_url: string;
  model: string;
  has_api_key: boolean;
  source: "account" | "system";
  revision?: string;
  dimensions?: number;
  send_dimensions?: boolean;
  vision?: boolean;
  structured_output?: "json_schema" | "json_object";
  enable_thinking?: boolean;
};

export type IndexProgress = { total: number; ready: number; failed: number; pending: number };

export type AccountModels = {
  version: number;
  llm: ModelConfig;
  embedding: ModelConfig;
  pending_embedding: ModelConfig | null;
  index: IndexProgress;
  rebuild: IndexProgress | null;
  queued?: boolean | null;
};
