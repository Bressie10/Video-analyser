import { LegalLayout, supportEmail } from './LegalLayout';

export function TermsPage() {
  return <LegalLayout title="Terms of Service">
    <section><h2>Acceptance of Terms</h2>
      <p>These Terms govern your use of ContentMetric (the Service), operated from Ireland. By using the Service, you agree to these Terms. If you do not agree, do not use the Service. If you use it for a company or another organisation, you must have authority to act on its behalf.</p>
    </section>
    <section><h2>Eligibility</h2>
      <p>You must be at least 16 years old and able to enter into these Terms under applicable law. You must have any permissions required to use the Service and to act for a workspace or connected account.</p>
    </section>
    <section><h2>Description of ContentMetric</h2>
      <p>ContentMetric analyses social-media content and available performance metrics to help users understand patterns and develop new content. It may generate content ideas, scripts, concepts, recommendations and analysis, and maintain company workspaces, feedback, idea states and publication associations.</p>
    </section>
    <section><h2>Beta and service availability</h2>
      <p>ContentMetric is an early public beta. Features may be incomplete, contain errors, change or become unavailable. We do not guarantee uninterrupted availability or preservation of every result. Keep your own copies of important content and output.</p>
      <p>The Service currently has no paid subscriptions, billing system or payment processing. Any future paid offering would be explained separately before you agree to charges.</p>
    </section>
    <section><h2>User responsibilities</h2>
      <p>Provide accurate information, protect your account access and credentials, and manage who is authorised to use your workspace. You are responsible for your use of the Service, your publishing decisions and compliance with applicable laws and the rights of others. Contact us if you suspect unauthorised use.</p>
    </section>
    <section><h2>Connected third-party accounts</h2>
      <p>Connect only accounts you are authorised to access and grant only permissions you are entitled to provide. You must comply with the terms and policies of Meta, Facebook, Instagram and any other service you use.</p>
      <p>Access depends on third-party permissions, services and APIs. ContentMetric does not control Meta availability, provider API availability, third-party account restrictions or provider policy changes. These may limit, interrupt or end a connection or change the information available.</p>
    </section>
    <section><h2>User content and permission to process it</h2>
      <p>You retain your rights to uploaded and connected social-media content. We do not claim ownership of that content. You give ContentMetric only the permission reasonably necessary to access, store, process and analyse it, including through service providers, to provide the Service and its requested outputs.</p>
      <p>You must have the rights and permissions needed to upload or connect content and allow this processing, including any required permissions concerning other people’s personal information. Do not submit content you are not entitled to use. Data retention and deletion are explained in our <a href="/privacy">Privacy Policy</a> and <a href="/data-deletion">Data Deletion Instructions</a>.</p>
    </section>
    <section><h2>AI-generated output</h2>
      <p>AI-generated ideas, scripts, concepts, recommendations and analysis can be incomplete, inaccurate, unsuitable or similar to output given to others. You are responsible for reviewing and checking output before publishing or relying on it, including factual claims, rights, permissions and suitability for your audience.</p>
      <p>Output is informational assistance, not legal, financial or other professional advice. We do not promise that output is original, exclusive or eligible for intellectual property protection.</p>
    </section>
    <section><h2>No performance guarantees</h2>
      <p>ContentMetric does not guarantee increased views, engagement or revenue, viral performance, marketing results or business results. Past metrics and suggested patterns do not predict future outcomes. Metrics may be incomplete, delayed or affected by provider limitations.</p>
    </section>
    <section><h2>Acceptable use</h2>
      <p>Do not use the Service for unlawful, deceptive or harmful activity, to infringe intellectual property or privacy rights, to upload malicious material, or to harass or exploit others. Do not attempt unauthorised access, misuse credentials, bypass access restrictions or provider limits, or disrupt the Service or its providers.</p>
    </section>
    <section><h2>Intellectual property</h2>
      <p>ContentMetric and its licensors retain their rights in the Service’s software, design and branding. These Terms allow you to use the Service for its intended purpose; they do not transfer ownership of it to you. Your existing rights in your content remain yours. Any rights in generated output depend on applicable law and relevant third-party rights.</p>
    </section>
    <section><h2>Third-party services</h2>
      <p>The Service relies on Vercel, Render, Supabase PostgreSQL, the OpenAI API, and Meta services including Facebook and Instagram. Third-party services have their own terms and privacy policies. We do not control or take responsibility for their independent systems, decisions or practices.</p>
    </section>
    <section><h2>Suspension and termination</h2>
      <p>You may stop using the Service at any time, disconnect connected accounts and request deletion of application data. We may restrict, suspend or end access where reasonably necessary to address misuse, security risks, breaches of these Terms or legal requirements, or if we discontinue the Service. Where reasonably possible, we will provide notice and an opportunity to address the issue.</p>
      <p>Disconnection or termination does not automatically erase all stored data. The Privacy Policy explains retention and your deletion options. Provisions that by their nature need to continue, including ownership, applicable liability limits and dispute provisions, survive termination.</p>
    </section>
    <section><h2>Service changes</h2>
      <p>We may add, change or remove features or discontinue the Service. We will give reasonable notice of significant changes where practicable, subject to urgent security, legal or operational needs.</p>
    </section>
    <section><h2>Disclaimers</h2>
      <p>To the extent permitted by law, the beta Service is provided “as is” and “as available”, without warranties of accuracy, reliability, fitness for a particular purpose or uninterrupted operation. Nothing in these Terms removes warranties or consumer protections that cannot lawfully be excluded.</p>
    </section>
    <section><h2>Limitation of liability</h2>
      <p>To the extent permitted by law, ContentMetric is not liable for indirect or consequential losses, or loss of profits, revenue, business opportunities or anticipated results arising from use of the Service or reliance on its output. You should take reasonable steps to protect important records and check publishing decisions.</p>
      <p>Nothing in these Terms excludes or limits liability for fraud, death or personal injury caused by negligence, or any liability or mandatory consumer right that cannot legally be excluded or limited.</p>
    </section>
    <section><h2>Governing law</h2>
      <p>These Terms are governed by the laws of Ireland, subject to any mandatory rights that may apply under the laws of your country of residence. Nothing here prevents you from using courts or other remedies available under those mandatory rights.</p>
    </section>
    <section><h2>Changes to the Terms</h2>
      <p>We may update these Terms and will show the updated date on this page. We will provide notice of material changes where appropriate or required. If you do not agree to revised Terms, stop using the Service. Changes do not remove rights you already have under applicable law.</p>
    </section>
    <section><h2>Contact</h2>
      <p>For questions about these Terms or the Service, email <a href={`mailto:${supportEmail}`}>{supportEmail}</a>. For privacy and deletion requests, see our <a href="/privacy">Privacy Policy</a> and <a href="/data-deletion">Data Deletion Instructions</a>.</p>
    </section>
  </LegalLayout>;
}
