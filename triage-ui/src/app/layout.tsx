import type { Metadata } from "next";
import "@fontsource-variable/schibsted-grotesk";
import "@fontsource-variable/newsreader";
import "./globals.css";

export const metadata: Metadata = {
  title: "Motif",
  description: "Turn customer feedback into a ranked, evidence-backed roadmap.",
};

// Apply the saved colour theme before the first paint, so the page never flashes the default one
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("motif-theme");if(t)document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
