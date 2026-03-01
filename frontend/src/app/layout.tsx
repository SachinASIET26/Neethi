import type { Metadata } from "next";
import "./globals.css";
import "@crayonai/react-ui/styles/index.css";
import { ThemeProvider } from "@/components/providers/ThemeProvider";

export const metadata: Metadata = {
  title: "Neethi AI — Indian Legal Intelligence",
  description:
    "Citation-verified, hallucination-free Indian legal AI. Powered by CrewAI with IRAC analysis, statute lookup, and document drafting for lawyers, citizens, and legal professionals.",
  keywords: ["Indian law", "legal AI", "BNS", "BNSS", "IPC", "legal research", "lawyer"],
  authors: [{ name: "Neethi AI" }],
  openGraph: {
    title: "Neethi AI — Indian Legal Intelligence",
    description: "Source-cited, verified Indian legal AI for lawyers, citizens, and legal professionals.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Merriweather:ital,wght@0,400;0,700;1,400;1,700&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-gray-50 dark:bg-[#020617] text-gray-900 dark:text-slate-100 font-display antialiased">
        <ThemeProvider>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
