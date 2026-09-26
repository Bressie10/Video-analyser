-- TEST ONLY. Minimal stand-ins for absent 006/007, not production migrations.
CREATE TABLE companies (id UUID PRIMARY KEY);
CREATE TABLE fixture_company_members (
 company_id UUID REFERENCES companies(id), connection_id UUID REFERENCES meta_connections(id),
 can_write BOOLEAN NOT NULL DEFAULT true, PRIMARY KEY(company_id,connection_id)
);
CREATE TABLE fixture_company_items (
 company_id UUID REFERENCES companies(id), item_id UUID REFERENCES meta_library_items(id) ON DELETE CASCADE,
 PRIMARY KEY(company_id,item_id)
);
CREATE TABLE fixture_profiles (
 company_id UUID PRIMARY KEY REFERENCES companies(id), revision_id UUID NOT NULL, payload JSONB NOT NULL
);
