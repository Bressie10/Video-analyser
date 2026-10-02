# V7 activation surfaces

These page states work without the V7 onboarding wizard. They use the existing V5 shell, company scope and hash navigation.

| Page state | Evidence used | Next action |
| --- | --- | --- |
| Content: no publishing source | Active company's linked accounts contain neither Instagram nor Facebook, and the unfiltered content response is empty | Settings, to connect Meta and link a publishing account |
| Content: linked but empty | Active company has Instagram or Facebook linked, and the unfiltered content response is empty | Settings, to review the linked accounts |
| Content: no analysis | The complete first unfiltered content page has items, with no `analyzed` item | Read item statuses in Content |
| Content: processing or failed | An item on the complete first unfiltered page has an existing queued/processing or failed `analysis_state` | Refresh the Content read to check current status |
| Generate: no analyzed sources | Existing company-scoped `listSources` response is empty | Content |
| Ideas: empty history, no publishing source | Ideas history response is empty and the company has no Instagram/Facebook account | Content |
| Ideas: empty history, publishing source linked | Ideas history response is empty and the company has a publishing account | Generate |

Filtered Content and Ideas results keep their existing search-specific states. Content guidance appears only when the complete unfiltered first page supports it; a paginated page cannot establish that the whole library has no analysis. Item badges continue to show each item's exact status. Generate retains the existing form and source-selection behavior when sources are present. An empty source response does not claim a Meta connection or a completed analysis.

## Assumptions and limits

The active company's account list establishes linkage to that company, not the live state of a Meta connection or discovery job. Refreshing Content re-reads status; it does not retry failed analysis. The mounted company Content page has no analysis selection, analysis retry or content sync action. The older global `VideoLibrary` has those controls but is not part of the current company-scoped navigation, so these surfaces do not invoke it. No onboarding progress is calculated here.

## Integration opportunities for onboarding Agent B

The Settings and Content links are useful hand-off points for future onboarding entry actions. Agent B can connect those destinations to its wizard without changing the page-level evidence checks or the existing generation API. If a company-scoped analysis action is later exposed on Content, the no-analysis and failed guidance can point to that action.
