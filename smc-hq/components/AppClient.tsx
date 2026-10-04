'use client';
import dynamic from 'next/dynamic';

const App = dynamic(() => import('./App'), {
  ssr: false,
  loading: () => <div className="intro" style={{ animation: 'none' }}><h1>SMC TRADING HQ</h1><p>BOOTING…</p></div>,
});

export default function AppClient() { return <App />; }
