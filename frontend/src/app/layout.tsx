import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: {
    default: "CodeJudge AI — Your next breakthrough",
    template: "%s · CodeJudge AI",
  },
  description:
    "A thoughtful Python challenge workspace. Write solutions, request evaluations, and understand your results.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body>{children}</body>
    </html>
  );
}
