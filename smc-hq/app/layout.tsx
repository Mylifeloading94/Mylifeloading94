import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'SMC TRADING HQ — 3D Agent World',
  description: 'Four AI agents. One market intelligence system. Educational analysis only — not financial advice.',
};
export const viewport: Viewport = { width: 'device-width', initialScale: 1, themeColor: '#0d0a24' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* Comic fonts. If the CDN is unreachable the stack falls back to Impact / Comic Sans / system fonts. */}
        <link href="https://fonts.googleapis.com/css2?family=Bangers&family=Comic+Neue:wght@700;900&family=Press+Start+2P&display=swap" rel="stylesheet" />
      </head>
      <body>{children}</body>
    </html>
  );
}
