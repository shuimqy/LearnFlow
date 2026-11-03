import type { Task } from "@/features/tasks/types";

export type Document = {
  id: string;
  course_id: string;
  filename: string;
  size_bytes: number;
  page_count: number;
  exercise_mode: string;
  status: string;
  created_at: string;
  task: Task;
};
