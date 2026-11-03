export type Conversation = {
  id: string;
  course_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  parent_conversation_id: string | null;
  parent_message_id: string | null;
  anchor_text: string;
  context_mode: "focused" | "full" | "minimal" | null;
  source_question: string;
  context_truncated: boolean;
  source_images: ChatImage[];
};
export type Citation = {
  key: string;
  knowledge_id: string;
  version: number;
  title: string;
  text: string;
  current: boolean;
  knowledge_status: string;
  sources: {
    document_id: string | null;
    filename: string;
    page_number: number;
    quote: string;
    available: boolean;
  }[];
};
export type ChatImage = {
  id: string;
  filename: string;
  media_type: string;
  size: number;
  width: number;
  height: number;
};
export type ChatMessage = {
  id: string;
  conversation_id: string;
  sequence: number;
  request_id: string;
  role: "user" | "assistant";
  content: string;
  images: ChatImage[];
  supplement: string;
  status: "pending" | "completed" | "generating" | "failed";
  workflow_stage: string | null;
  citations: Citation[];
  warnings: string[];
  error: string | null;
  retrieval_mode: string | null;
  model: string | null;
};
export type IndexStatus = {
  rebuild?: { model: string; total: number; ready: number; failed: number; pending: number };
  total: number;
  ready: number;
  pending: number;
  failed: number;
  embedding_configured: boolean;
  llm_configured: boolean;
  llm_vision: boolean;
};
