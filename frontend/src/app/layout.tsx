import type { Metadata } from "next";
import { AuthProvider } from "@/features/auth/auth-provider";
import "katex/dist/katex.min.css";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "LearnFlow · 我的课程", template: "%s · LearnFlow" },
  description: "课程资料、知识库、问答与做题本。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
