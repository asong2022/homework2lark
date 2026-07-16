import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "教师精选框题",
  description: "面向小学数学教师的手动与自动框题工具",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="site-frame">
          <div className="site-brand" aria-label="教师精选框题">
            <span className="brand-mark">选</span>
            <span>
              <strong>教师精选框题</strong>
              <small>错题学习系统</small>
            </span>
          </div>
          {children}
        </div>
      </body>
    </html>
  );
}
