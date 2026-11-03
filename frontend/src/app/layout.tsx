import type { Metadata } from "next";
import { AuthProvider } from "@/context/AuthContext";
import "./globals.css";

export const metadata: Metadata = {
  title: "VisorQA — Autonomous Visual QA & Self-Healing Agent",
  description: "Detects pixel-level regressions with Meta SAM 3.1 & heals CSS layout defects with Muse models.",
  icons: {
    icon: [
      { url: "/favicon.ico" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/icon.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [
      { url: "/apple-icon.png", sizes: "180x180", type: "image/png" },
    ],
    shortcut: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark font-sans">
      <body
        className="antialiased bg-canvas text-text-primary min-h-screen"
      >
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
