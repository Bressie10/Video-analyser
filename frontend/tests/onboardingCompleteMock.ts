// Legacy V5/V6 browser fixtures predate the V7 backend. Keep them focused on
// their existing flows while the dedicated onboarding tests mock the real API.
export class OnboardingError extends Error { constructor(readonly status: number) { super('Onboarding request failed.'); } }
export const onboardingApi = {
  async get() { return { company_id: null, welcome_seen: true, skipped: false, progress: 100, complete: true, next_step: null,
    steps: { workspace: true, meta: true, account: true, analysis: true, idea: true } }; },
  async welcome() {}, async skip() {}, async company() {},
};
