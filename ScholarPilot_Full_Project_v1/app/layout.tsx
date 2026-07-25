import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ScholarPilot · 可追踪学术检索",
  description:
    "把复杂科研问题拆成可执行、可核验的真实论文检索与证据排序过程。",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
