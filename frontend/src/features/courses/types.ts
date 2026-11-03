export type CourseColor = "sage" | "sand" | "blue" | "rose" | "lavender";
export type Course = {
  id: string;
  name: string;
  description: string;
  color: CourseColor;
  document_count: number;
  created_at: string;
  updated_at: string;
};
export type CourseInput = Pick<Course, "name" | "description" | "color">;
