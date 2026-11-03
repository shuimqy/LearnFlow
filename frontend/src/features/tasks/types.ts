export type Task = {
  id: string;
  document_id: string;
  status: string;
  stage: string;
  progress: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  filename: string | null;
  course_id: string | null;
  course_name: string | null;
};
