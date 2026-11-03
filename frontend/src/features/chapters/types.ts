export type Chapter = {
  id: string;
  document_id: string;
  filename: string;
  title: string;
  start_page: number;
  end_page: number;
  source: string;
  knowledge_count: number;
  exercise_count: number;
};
export type StructureState = {
  version: number;
  status: string;
  progress: number;
  error: string | null;
  warnings: string[];
  chapters: Chapter[];
};
