BEGIN;

-- A refresh request must point to a job owned by the same profile, not merely
-- to any existing profile and any existing job. Validate existing data; do not
-- silently rewrite an inconsistent idempotency record during an upgrade.
ALTER TABLE company_profile_jobs ADD CONSTRAINT company_profile_jobs_profile_key
    UNIQUE (profile_id, id);
ALTER TABLE company_profile_refresh_requests
    DROP CONSTRAINT company_profile_refresh_requests_job_id_fkey;
ALTER TABLE company_profile_refresh_requests
    ADD CONSTRAINT company_profile_refresh_requests_profile_job_fk
    FOREIGN KEY (profile_id, job_id) REFERENCES company_profile_jobs(profile_id, id);

COMMIT;
