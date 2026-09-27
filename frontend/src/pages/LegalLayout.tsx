import { useEffect, type ReactNode } from 'react';
import './legal.css';

export const privacyEmail = 'privacy@contentmetric.app';
export const supportEmail = 'support@contentmetric.app';

export function LegalFooter() {
  return <footer className="legal-footer">
    <span>ContentMetric</span>
    <nav aria-label="Legal">
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <a href="/data-deletion">Data Deletion</a>
    </nav>
  </footer>;
}

export function LegalLayout({ title, documentTitle = title, children }: { title: string; documentTitle?: string; children: ReactNode }) {
  useEffect(() => { document.title = `${documentTitle} | ContentMetric`; }, [documentTitle]);
  return <>
    <main className="legal-page">
      <a className="legal-back" href="/">Back to ContentMetric</a>
      <article aria-labelledby="legal-title">
        <header>
          <p className="eyebrow">ContentMetric</p>
          <h1 id="legal-title">{title}</h1>
          <p className="muted">Last updated: <time dateTime="2026-09-27">27 September 2026</time></p>
        </header>
        {children}
      </article>
    </main>
    <LegalFooter />
  </>;
}
