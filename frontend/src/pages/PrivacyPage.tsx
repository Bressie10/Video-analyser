import { LegalLayout, privacyEmail, supportEmail } from './LegalLayout';

export function PrivacyPage() {
  return <LegalLayout title="Privacy Policy">
    <section>
      <h2>About this policy</h2>
      <p>ContentMetric is an Ireland-based social-media content analysis and AI-assisted content idea generation service. This policy explains how we handle personal information when you use the Service, connect social accounts or contact us. ContentMetric is responsible for the processing described here; connected providers remain responsible for their own systems.</p>
      <p>Contact us about privacy at <a href={`mailto:${privacyEmail}`}>{privacyEmail}</a>, or for general support at <a href={`mailto:${supportEmail}`}>{supportEmail}</a>.</p>
    </section>
    <section>
      <h2>Information we process</h2>
      <p>Depending on the features you use and the permissions available, we may process:</p>
      <ul>
        <li>Connected Meta account, Facebook Page and Instagram account information, including account and service identifiers needed for integration.</li>
        <li>Accessible social-media content metadata, including video, post, reel and ad metadata, and public or otherwise permitted performance metrics.</li>
        <li>Content analysis results, generated content ideas, scripts, concepts and recommendations.</li>
        <li>Company and workspace configuration, feedback such as liked or disliked ideas, idea lifecycle states, and publication associations between ideas and content.</li>
        <li>Encrypted provider tokens used to maintain connected services, and temporarily uploaded media used for processing.</li>
        <li>Information you provide in support or privacy requests, and technical information reasonably needed to operate, troubleshoot and secure the Service.</li>
      </ul>
      <p>Information comes from you, authorised workspace activity, connected services within the access they permit, and analysis performed by ContentMetric. Please only provide information and content you have permission to use.</p>
    </section>
    <section>
      <h2>How and why we use information</h2>
      <p>We use this information to analyse social-media content, understand performance patterns, generate content recommendations and ideas, maintain your workspace and provider connections, and improve the relevance of recommendations using workspace context and feedback. We also use information to provide support, operate and secure the Service, prevent misuse and meet applicable legal obligations.</p>
      <p>Where EU/EEA data protection law applies, our legal basis depends on the purpose: performing our agreement with you where processing is necessary to provide the Service; legitimate interests in maintaining a useful, reliable and secure service, balanced against your rights; compliance with legal obligations; or consent where required. Where we rely on consent, you may withdraw it without affecting the lawfulness of earlier processing.</p>
    </section>
    <section>
      <h2>Service providers and sharing</h2>
      <p>We use Vercel for frontend hosting, Render for backend hosting, Supabase PostgreSQL for database storage, the OpenAI API for AI processing, and Meta, including Facebook and Instagram, for social integrations. Relevant information may be processed by these providers as needed for their role; for example, content analysis and workspace context may be sent to the OpenAI API to generate recommendations.</p>
      <p>Information within a shared company or workspace may be available to people authorised to use it. We may also disclose information where reasonably necessary to meet legal obligations, protect rights or address security incidents.</p>
      <p>Third-party services operate under their own privacy policies and terms. ContentMetric does not control their systems or their independent handling of information. Processing may take place outside Ireland or the EEA, depending on provider arrangements. Where required, international transfers must use applicable safeguards, such as recognised adequacy decisions or standard contractual clauses. Contact us for information about safeguards relevant to your data.</p>
    </section>
    <section>
      <h2>Storage and retention</h2>
      <p>Temporary uploaded or processing media is intended to be removed after processing. Derived data may remain, including metadata, analysis results, metrics, generated ideas, feedback, company and workspace records, and associations between ideas and content.</p>
      <p>Application data may be retained while reasonably necessary to provide the Service, maintain your workspace, maintain security or comply with legitimate legal requirements. Retention depends on the data and purpose; we do not specify a single fixed period.</p>
      <p>You can request deletion using our <a href="/data-deletion">Data Deletion Instructions</a>. We aim to handle valid deletion requests within 30 days where reasonably possible, subject to applicable legal deadlines. Disconnecting a provider does not necessarily erase data already stored by ContentMetric.</p>
    </section>
    <section>
      <h2>Security</h2>
      <p>We use reasonable technical and organisational measures to protect information. Provider tokens are intended to be stored server-side, encrypted and not exposed directly in the normal frontend interface. No system or method of transmission can be guaranteed secure. Please protect access to your accounts and never send passwords, access tokens or API keys in support or privacy emails.</p>
    </section>
    <section>
      <h2>Your privacy rights</h2>
      <p>Depending on the applicable law and circumstances, including for people in the EU/EEA, you may have rights to access, correct or delete personal data, restrict processing, object to certain processing, receive portable data where applicable, and withdraw consent where processing depends on consent. These rights have conditions and exceptions; not every right applies to every use of data.</p>
      <p>Email <a href={`mailto:${privacyEmail}`}>{privacyEmail}</a> to exercise your rights. We may need proportionate information to verify your identity and locate the relevant records, and will explain any applicable limits or reasons we cannot fully fulfil a request.</p>
      <p>You may raise a concern with the <a href="https://www.dataprotection.ie/en/individuals">Irish Data Protection Commission</a> or another competent data protection authority, including in your country of residence where applicable.</p>
    </section>
    <section>
      <h2>Local storage and connected sessions</h2>
      <p>The application uses browser storage to remember workspace choices and session information to support connected services. Clearing browser storage or disconnecting an account does not itself delete application records held on our servers.</p>
    </section>
    <section>
      <h2>Age requirement</h2>
      <p>You must be at least 16 years old to use ContentMetric. The Service is not intended for children under 16. If you believe a child under 16 has provided personal information, please contact us.</p>
    </section>
    <section>
      <h2>Changes to this policy</h2>
      <p>We may update this policy as the Service or our practices change. We will update the date on this page and provide further notice of material changes where appropriate or required. See also our <a href="/terms">Terms of Service</a>.</p>
    </section>
  </LegalLayout>;
}
