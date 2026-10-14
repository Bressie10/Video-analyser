import type { Citation, Metric } from '../intelligence/intelligenceModel';

export type ComparisonHandoff = {
  creativeRef: string; videoRef: string; label: string; group: 'higher' | 'lower';
  metric: Metric; metricValue: string; currency?: string; start: string; stop: string;
  accountName: string; selectedSignal?: string; citation?: Citation;
  citations: { signal: string; citation: Citation }[]; scrollY: number;
};
let current: ComparisonHandoff | null = null;
export function openCreative(context: ComparisonHandoff) {
  current = context;
  window.location.hash = `creative/${context.creativeRef}`;
}
export function comparisonFor(ref: string) { return current?.creativeRef === ref ? current : null; }
export function comparisonScroll() { return current?.scrollY ?? 0; }
