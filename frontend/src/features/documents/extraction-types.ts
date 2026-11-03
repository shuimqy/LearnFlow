import type { Task } from "@/features/tasks/types";

export type Formula = { latex: string; explanation: string; uncertain: boolean };
export type Example = {
  kind: "worked_example" | "exercise";
  title: string;
  question: string;
  answer: string;
  solution: string;
  formulas: Formula[];
  warnings: string[];
};
export type Draft = {
  id: string;
  kind: string;
  title: string;
  summary: string;
  content: string;
  formulas: Formula[];
  warnings: string[];
  example: Example | null;
  status: string;
  knowledge_id: string | null;
};
export type PageSummary = {
  id: string;
  page_number: number;
  status: string;
  warnings: string[];
  error: string | null;
  counts: Record<string, number>;
};
export type Extraction = {
  document_id: string;
  page_count: number;
  task: Task;
  pages: PageSummary[];
};
export type ExtractionPage = PageSummary & { transcript: string; drafts: Draft[] };
