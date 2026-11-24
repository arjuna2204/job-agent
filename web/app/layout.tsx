import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Job Agent",
  description: "Tell it what jobs you want. It finds them daily and fills the applications you approve.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
