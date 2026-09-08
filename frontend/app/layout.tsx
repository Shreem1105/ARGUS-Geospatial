import type { Metadata } from "next";

import { AppShell } from "@/components/shell/app-shell";
import { Providers } from "@/lib/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "ARGUS Geospatial Intelligence",
  description: "Explore and monitor geospatial change with ARGUS.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
