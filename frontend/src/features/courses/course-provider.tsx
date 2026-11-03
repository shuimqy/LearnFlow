"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/http";
import type { Course } from "./types";

type CourseState = {
  courses: Course[];
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
};
const CourseContext = createContext<CourseState | null>(null);

export function CourseProvider({ children }: { children: React.ReactNode }) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    setError("");
    try {
      setCourses(await api<Course[]>("/courses"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  return (
    <CourseContext.Provider value={{ courses, loading, error, refresh }}>
      {children}
    </CourseContext.Provider>
  );
}

export function useCourses() {
  const value = useContext(CourseContext);
  if (!value) throw new Error("CourseProvider is missing");
  return value;
}
