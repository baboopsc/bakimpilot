import type { Metadata } from "next";
import { Fira_Code, Fira_Sans } from "next/font/google";

import "./globals.css";
import { Providers } from "./providers";

const firaSans = Fira_Sans({
  subsets: ["latin", "latin-ext"], // latin-ext covers Turkish characters
  weight: ["400", "500", "600", "700"],
  variable: "--font-fira-sans",
});
const firaCode = Fira_Code({ subsets: ["latin"], variable: "--font-fira-code" });

export const metadata: Metadata = {
  title: "BakımPilot",
  description: "UAV fleet maintenance & airworthiness management",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${firaSans.variable} ${firaCode.variable}`}>
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
