import type { Metadata } from "next";
import { Bricolage_Grotesque, Instrument_Sans, Space_Mono } from "next/font/google";
import "./globals.css";

// Display font: distinctive variable grotesk, used for headlines only.
const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
});

// Body/workhorse font: clean but not Inter — used for everything else.
const instrument = Instrument_Sans({
  variable: "--font-instrument",
  subsets: ["latin"],
});

// Mono accent: used sparingly for labels, tags, numbers — a texture, not a paragraph font.
const spaceMono = Space_Mono({
  variable: "--font-space-mono",
  subsets: ["latin"],
  weight: ["400", "700"],
});

export const metadata: Metadata = {
  title: "Hackathon Frontend Starter",
  description: "A Next.js + Tailwind starter tuned to avoid the generic AI-website look.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${bricolage.variable} ${instrument.variable} ${spaceMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-bg text-fg">{children}</body>
    </html>
  );
}
