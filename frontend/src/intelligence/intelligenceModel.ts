export type Metric = 'ctr' | 'cpc' | 'cpm' | 'impressions';
export type Citation = {
  video_ref: string; evidence_ref: string; evidence_type: 'frame' | 'ocr' | 'transcript' | 'scene';
  timestamp_seconds: number; excerpt?: string;
};
export type Cited = { citation: Citation; role: 'support' | 'counterexample' };
export type Difference = {
  description: string; evidence_type: string; more_common_in?: string | null;
  earlier_in?: string | null; higher_group_support: number; lower_group_support: number;
  higher_group_size: number; lower_group_size: number; supporting_video_refs: string[];
  confidence: string; evidence_refs: Citation[]; counterexamples: Citation[];
  timing?: { higher_median_seconds: number; lower_median_seconds: number; relation: string } | null;
};
export type Hypothesis = {
  hypothesis: string; variable_to_test: string; control_condition: string; variant_condition: string;
  primary_metric: Metric; what_to_hold_constant: string[]; limitations: string[];
  counterevidence: Citation[]; source_difference: string;
};
export type Member = { video_ref: string; creative_ref?: string; metric_value: string; percentile: number | null };
export type Preview = { video_ref: string; frame_ref: string; timestamp_seconds: number; jpeg_base64: string };
export type IntelligenceResult = {
  metric: { description: string; unit?: string };
  cohort: { date_start: string; date_stop: string; distinct_ads?: number; peer_count: number;
    currency?: string; content_groups?: { higher: Member[]; lower: Member[]; middle_excluded_count: number } };
  performance: null | { summary: string; metric_facts: { target_value: string; median: string;
    ratio: string | null; percentile: number; description: string }; limitations: string[] };
  content_differences: Difference[]; hypotheses: Hypothesis[]; creative_previews: Preview[];
  abstentions: string[];
};

export const metrics: { id: Metric; label: string }[] = [
  { id: 'ctr', label: 'CTR' }, { id: 'cpc', label: 'CPC' },
  { id: 'cpm', label: 'CPM' }, { id: 'impressions', label: 'Impressions' },
];
export const metricLabel = (metric: Metric) => metrics.find(item => item.id === metric)?.label ?? metric;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const string = (value: unknown): value is string => typeof value === 'string';
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const count = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(string);
const metric = (value: unknown): value is Metric => metrics.some(item => item.id === value);
const numberString = (value: unknown): value is string =>
  string(value) && value.length < 80 && value.trim() !== '' && Number.isFinite(Number(value)) && Number(value) >= 0;

function citation(value: unknown): value is Citation {
  return record(value) && string(value.video_ref) && value.video_ref.length <= 120 &&
    string(value.evidence_ref) && value.evidence_ref.length <= 240 &&
    ['frame', 'ocr', 'transcript', 'scene'].includes(String(value.evidence_type)) &&
    finite(value.timestamp_seconds) && value.timestamp_seconds >= 0 &&
    (value.excerpt === undefined || string(value.excerpt) && value.excerpt.length <= 500);
}
function member(value: unknown): value is Member {
  return record(value) && string(value.video_ref) && value.video_ref.length <= 120 &&
    (value.creative_ref === undefined || string(value.creative_ref) && /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value.creative_ref)) &&
    numberString(value.metric_value) &&
    (value.percentile === null || finite(value.percentile) && value.percentile >= 0 && value.percentile <= 100);
}
function difference(value: unknown): value is Difference {
  return record(value) && string(value.description) && value.description.length <= 1000 &&
    string(value.evidence_type) && count(value.higher_group_support) && count(value.lower_group_support) &&
    count(value.higher_group_size) && count(value.lower_group_size) &&
    value.higher_group_support <= value.higher_group_size && value.lower_group_support <= value.lower_group_size &&
    strings(value.supporting_video_refs) && string(value.confidence) &&
    Array.isArray(value.evidence_refs) && value.evidence_refs.every(citation) &&
    Array.isArray(value.counterexamples) && value.counterexamples.every(citation) &&
    (value.timing === undefined || value.timing === null || record(value.timing) &&
      finite(value.timing.higher_median_seconds) && finite(value.timing.lower_median_seconds) &&
      string(value.timing.relation));
}
function hypothesis(value: unknown): value is Hypothesis {
  return record(value) && string(value.hypothesis) && string(value.variable_to_test) &&
    string(value.control_condition) && string(value.variant_condition) && metric(value.primary_metric) &&
    strings(value.what_to_hold_constant) && strings(value.limitations) && string(value.source_difference) &&
    Array.isArray(value.counterevidence) && value.counterevidence.every(citation);
}
function preview(value: unknown): value is Preview {
  return record(value) && string(value.video_ref) && string(value.frame_ref) &&
    finite(value.timestamp_seconds) && value.timestamp_seconds >= 0 &&
    string(value.jpeg_base64) && value.jpeg_base64.length <= 90000 &&
    /^[A-Za-z0-9+/]+={0,2}$/.test(value.jpeg_base64);
}

export function parseIntelligence(value: unknown): IntelligenceResult {
  if (!record(value) || !record(value.metric) || !string(value.metric.description) ||
      !record(value.cohort) || !string(value.cohort.date_start) || !string(value.cohort.date_stop) ||
      !count(value.cohort.peer_count) ||
      !Array.isArray(value.content_differences) || !value.content_differences.every(difference) ||
      !Array.isArray(value.hypotheses) || value.hypotheses.length > 3 || !value.hypotheses.every(hypothesis) ||
      !strings(value.abstentions) ||
      (value.creative_previews !== undefined && (!Array.isArray(value.creative_previews) ||
        value.creative_previews.length > 6 || !value.creative_previews.every(preview)))) {
    throw new Error('Malformed intelligence response');
  }
  const cohort = value.cohort;
  const groups = cohort.content_groups;
  if (groups !== undefined && (!record(groups) || !Array.isArray(groups.higher) ||
      !Array.isArray(groups.lower) || groups.higher.length !== 3 || groups.lower.length !== 3 ||
      !groups.higher.every(member) || !groups.lower.every(member) || !count(groups.middle_excluded_count) ||
      new Set([...groups.higher, ...groups.lower].map(row => row.video_ref)).size !== 6)) {
    throw new Error('Malformed intelligence groups');
  }
  const performance = value.performance;
  if (performance !== null && (!record(performance) || !string(performance.summary) ||
      !record(performance.metric_facts) || !numberString(performance.metric_facts.target_value) ||
      !numberString(performance.metric_facts.median) ||
      !(performance.metric_facts.ratio === null || numberString(performance.metric_facts.ratio)) ||
      !finite(performance.metric_facts.percentile) || performance.metric_facts.percentile < 0 ||
      performance.metric_facts.percentile > 100 || !string(performance.metric_facts.description) ||
      !strings(performance.limitations))) {
    throw new Error('Malformed intelligence performance');
  }
  return { metric: value.metric as IntelligenceResult['metric'],
    cohort: cohort as IntelligenceResult['cohort'], performance: performance as IntelligenceResult['performance'],
    content_differences: value.content_differences as Difference[],
    hypotheses: value.hypotheses as Hypothesis[],
    creative_previews: (value.creative_previews ?? []) as Preview[], abstentions: value.abstentions };
}

export function formatMetric(value: string, metricId: Metric, currency?: string) {
  const number = Number(value);
  const digits = metricId === 'impressions' ? 0 : 3;
  const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(number);
  if (metricId === 'ctr') return `${formatted}%`;
  if (metricId === 'cpc' || metricId === 'cpm') return `${currency ? `${currency} ` : ''}${formatted}`;
  return formatted;
}
export function formatRatio(value: string | null) {
  return value === null ? 'Unavailable' : `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Number(value))}×`;
}
export function formatPercentile(value: number) {
  const shown = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
  const integer = Number.isInteger(value);
  const mod100 = value % 100;
  const suffix = !integer || mod100 >= 11 && mod100 <= 13 ? 'th'
    : value % 10 === 1 ? 'st' : value % 10 === 2 ? 'nd' : value % 10 === 3 ? 'rd' : 'th';
  return `${shown}${suffix} percentile`;
}
export function timeLabel(value: number) {
  return `${new Intl.NumberFormat(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 }).format(value)}s`;
}
export function citations(difference: Difference): Cited[] {
  const counter = new Set(difference.counterexamples.map(item => item.evidence_ref));
  const seen = new Set<string>();
  return [...difference.evidence_refs, ...difference.counterexamples].flatMap(citation => {
    if (seen.has(citation.evidence_ref)) return [];
    seen.add(citation.evidence_ref);
    return [{ citation, role: counter.has(citation.evidence_ref) ? 'counterexample' as const : 'support' as const }];
  });
}
