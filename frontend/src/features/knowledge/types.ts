export type KnowledgeSource = {
  id: string;
  document_id: string | null;
  fragment_id: string | null;
  filename: string;
  page_number: number;
  quote: string;
};

export type SourceInput = {
  document_id: string | null;
  source_id?: string;
  page_number: number;
  quote: string;
};

export type KnowledgeInput = {
  title: string;
  summary: string;
  content: string;
  sources: SourceInput[];
};

export type KnowledgePoint = Omit<KnowledgeInput, "sources"> & {
  id: string;
  course_id: string;
  version: number;
  status: "active" | "archived";
  sources: KnowledgeSource[];
  created_at: string;
  updated_at: string;
};

export type Snapshot = Omit<KnowledgeInput, "sources"> & {
  sources: Omit<KnowledgeSource, "id">[];
  status?: string;
};

export type Revision = {
  id: string;
  version: number;
  snapshot: Snapshot;
  operation: string;
  reason: string;
  created_at: string;
};

export type Proposal = {
  id: string;
  knowledge_id: string;
  base_version: number;
  proposed: Snapshot;
  reason: string;
  status: "pending" | "accepted" | "rejected" | "superseded";
  created_at: string;
  processing: boolean;
  llm_review: ProposalProcessing | null;
};

export type ProposalProcessing = {
  outcome: "applied" | "rejected" | "needs_evidence" | "stale" | "unchanged" | "error";
  applied: boolean;
  applied_version?: number | null;
  message: string;
  model?: string;
  verdict?: "approve" | "revise" | "reject" | "needs_evidence";
  basis?: "source" | "reasoning" | "insufficient";
  opinion?: string;
  reasons?: string[];
  changes?: string[];
  warnings?: string[];
  content?: string;
  evidence?: { source_key: string; observation: string }[];
  sources?: {
    source_key: string;
    document_id: string | null;
    page_number: number;
    filename: string;
    note: string;
  }[];
};

export type KnowledgeStats = {
  active: number;
  archived: number;
  pending_proposals: number;
  chunks: number;
  search_mode: "text";
};

export type ExtractedPage = {
  id: string;
  page_number: number;
  text: string;
  status: "extracted" | "empty" | "needs_ocr";
};
