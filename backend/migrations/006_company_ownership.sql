BEGIN;

-- Alternate keys support ownership FKs without conflating provider namespaces,
-- library item IDs, and analysis video IDs.
ALTER TABLE meta_accounts ADD CONSTRAINT meta_accounts_ownership_key
    UNIQUE (id, connection_id, platform);
ALTER TABLE meta_accounts ADD CONSTRAINT meta_accounts_connection_key
    UNIQUE (id, connection_id);
ALTER TABLE meta_library_items ADD CONSTRAINT meta_items_ownership_key
    UNIQUE (id, connection_id, account_id, content_type);
ALTER TABLE meta_library_items ADD CONSTRAINT meta_items_connection_key
    UNIQUE (id, connection_id);
ALTER TABLE videos ADD CONSTRAINT videos_connection_key
    UNIQUE (id, meta_connection_id);
ALTER TABLE meta_sync_runs ADD CONSTRAINT meta_runs_connection_key
    UNIQUE (id, connection_id);

-- Preserve even inconsistent historical V2 rows. These constraints enforce new
-- relationships; company readers must still check every existing relationship.
ALTER TABLE meta_library_items ADD CONSTRAINT meta_items_account_connection_fk
    FOREIGN KEY (account_id, connection_id)
    REFERENCES meta_accounts (id, connection_id) NOT VALID;
ALTER TABLE meta_library_items ADD CONSTRAINT meta_items_video_connection_fk
    FOREIGN KEY (video_id, connection_id)
    REFERENCES videos (id, meta_connection_id) NOT VALID;
ALTER TABLE meta_accounts ADD CONSTRAINT meta_accounts_run_connection_fk
    FOREIGN KEY (initial_run_id, connection_id)
    REFERENCES meta_sync_runs (id, connection_id) NOT VALID;
ALTER TABLE meta_jobs ADD CONSTRAINT meta_jobs_run_connection_fk
    FOREIGN KEY (run_id, connection_id)
    REFERENCES meta_sync_runs (id, connection_id) ON DELETE CASCADE NOT VALID;
ALTER TABLE meta_jobs ADD CONSTRAINT meta_jobs_item_connection_fk
    FOREIGN KEY (item_id, connection_id)
    REFERENCES meta_library_items (id, connection_id) ON DELETE CASCADE NOT VALID;

CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES meta_connections(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    CONSTRAINT companies_connection_key UNIQUE (id, connection_id)
);
CREATE INDEX companies_connection ON companies(connection_id);

CREATE TABLE company_accounts (
    company_id UUID NOT NULL,
    connection_id UUID NOT NULL,
    account_id UUID NOT NULL,
    account_platform TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, account_id),
    CONSTRAINT company_accounts_ownership_key
        UNIQUE (company_id, connection_id, account_id, account_platform),
    CONSTRAINT company_accounts_company_fk
        FOREIGN KEY (company_id, connection_id)
        REFERENCES companies(id, connection_id) ON DELETE RESTRICT,
    CONSTRAINT company_accounts_account_fk
        FOREIGN KEY (account_id, connection_id, account_platform)
        REFERENCES meta_accounts(id, connection_id, platform) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX company_accounts_one_organic_owner
    ON company_accounts(account_id) WHERE account_platform IN ('facebook','instagram');
CREATE INDEX company_accounts_account ON company_accounts(account_id);

CREATE TABLE company_ad_assignments (
    ad_item_id UUID PRIMARY KEY,
    company_id UUID NOT NULL,
    connection_id UUID NOT NULL,
    account_id UUID NOT NULL,
    account_platform TEXT NOT NULL DEFAULT 'meta_ads' CHECK (account_platform = 'meta_ads'),
    content_type TEXT NOT NULL DEFAULT 'ad' CHECK (content_type = 'ad'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT company_ad_assignments_link_fk
        FOREIGN KEY (company_id, connection_id, account_id, account_platform)
        REFERENCES company_accounts(company_id, connection_id, account_id, account_platform)
        ON DELETE RESTRICT,
    CONSTRAINT company_ad_assignments_item_fk
        FOREIGN KEY (ad_item_id, connection_id, account_id, content_type)
        REFERENCES meta_library_items(id, connection_id, account_id, content_type)
        ON DELETE RESTRICT
);
CREATE INDEX company_ad_assignments_company_account
    ON company_ad_assignments(company_id, account_id);

COMMIT;
