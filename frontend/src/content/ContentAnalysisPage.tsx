import { CreativeAnalysisPage } from '../creativeAnalysis/CreativeAnalysisPage';

/** The evidence inspector is shared with Creative Intelligence; this entry uses company content scope. */
export function ContentAnalysisPage({ itemId }: { itemId: string }) {
  return <CreativeAnalysisPage contentItemId={itemId} />;
}
