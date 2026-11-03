export type Exercise = {
  draft_id: string;
  source_version: number;
  title: string;
  question: string;
  answer: string;
  solution: string;
  kind: "exercise" | "worked_example";
  document_id: string;
  filename: string;
  page_number: number;
  knowledge_id: string;
  warnings: string[];
  question_type?: string;
  difficulty?: string;
  knowledge_tags?: string[];
  chapter?: { id: string; title: string } | null;
  layout_version?: number;
  crop_status?: string;
  assets?: { id: string; role: "question" | "figure"; position: number }[];
  asset_scope?: "source" | "workbook";
};

export type Section = { title: string; items: Exercise[] };
export type WorkbookSettings = {
  print_mode?: "text" | "original";
  include_answers: boolean;
  answer_space: "compact" | "medium" | "large" | "page";
  show_sources: boolean;
};
export type WorkbookSummary = {
  id: string;
  title: string;
  course_id: string;
  version: number;
  updated_at: string;
};
export type Workbook = WorkbookSummary & {
  sections: Section[];
  settings: WorkbookSettings;
};
