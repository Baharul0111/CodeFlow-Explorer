import type { Metadata } from "next";
import { Bricolage_Grotesque, JetBrains_Mono, Source_Sans_3 } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-bricolage",
  weight: ["500", "600", "700"],
  display: "swap",
});

const body = Source_Sans_3({
  subsets: ["latin"],
  variable: "--font-source-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "CodeFlow Explorer",
  description: "Upload a project and read how it works as a flow you can open up, step by step.",
};

/** Applies the saved theme before first paint so the page never flashes the wrong one. */
const THEME_SCRIPT = `try{var t=localStorage.getItem("codeflow-theme");if(t==="dark"||t==="light"){document.documentElement.dataset.theme=t}}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${mono.variable} h-full`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
