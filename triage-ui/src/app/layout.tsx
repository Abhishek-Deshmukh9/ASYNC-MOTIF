import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Motif — Feedback Intelligence",
  description: "Turn customer feedback into an evidence-backed roadmap.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
