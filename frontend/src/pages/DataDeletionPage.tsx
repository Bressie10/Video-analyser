import { LegalLayout, privacyEmail } from './LegalLayout';

export function DataDeletionPage() {
  return <LegalLayout title="Data Deletion Instructions" documentTitle="Data Deletion">
    <section><h2>Request deletion by email</h2>
      <p>ContentMetric currently handles deletion requests manually by email. To request deletion of your ContentMetric data, email <a href={`mailto:${privacyEmail}`}>{privacyEmail}</a>. You do not need to log in or have an active Meta connection to make a request.</p>
      <p>Please include:</p>
      <ul>
        <li>A statement that your request concerns ContentMetric.</li>
        <li>Enough identifying information to locate the relevant account or workspace, such as the email or account identifier you used with the Service.</li>
        <li>The connected Facebook or Instagram account, or the company or workspace involved, where applicable.</li>
        <li>What data you want deleted, including whether you are requesting deletion of all relevant application-held data.</li>
      </ul>
      <p><strong>Do not send passwords, Meta access tokens, API keys, authentication secrets, payment details or other sensitive credentials.</strong> Share only the information needed to identify the relevant records. We may ask for proportionate verification of your identity or authority over a workspace before acting.</p>
    </section>
    <section><h2>What a request can cover</h2>
      <p>A request may cover application-held connected-account records, imported content metadata, stored analysis results, performance records, generated ideas, feedback, company and workspace records, and publication associations between ideas and content. You can ask us to clarify the scope if you are unsure which records relate to you.</p>
    </section>
    <section><h2>Timing and limited retention</h2>
      <p>We aim to process valid deletion requests within 30 days where reasonably possible, subject to applicable legal deadlines. If we need clarification or cannot fully fulfil a request, we will explain the reason and any relevant next steps.</p>
      <p>Some minimal information may need to be retained where reasonably required for security, fraud prevention, legal obligations or resolving disputes. Any such retention should be limited to what is necessary for that purpose.</p>
    </section>
    <section><h2>Facebook, Instagram and Meta data</h2>
      <p>Disconnecting Facebook or Instagram from ContentMetric does not necessarily delete all data previously stored by ContentMetric. Use the email process above to request deletion of application-held data.</p>
      <p>Deleting ContentMetric data does not necessarily delete content or information held directly by Meta. ContentMetric does not control or delete information in Meta’s independent systems. You may also need to manage that information through your Facebook, Instagram or Meta account settings.</p>
    </section>
    <section><h2>More information</h2>
      <p>Read our <a href="/privacy">Privacy Policy</a> for information about processing, retention and privacy rights, and our <a href="/terms">Terms of Service</a> for the conditions of using ContentMetric.</p>
    </section>
  </LegalLayout>;
}
