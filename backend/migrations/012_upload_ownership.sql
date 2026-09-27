BEGIN;
-- Existing uploads remain unclaimed; only verified new uploads receive an owner.
ALTER TABLE videos ADD COLUMN owner_user_id UUID REFERENCES user_profiles(user_id);
CREATE INDEX videos_owner_user_id_idx ON videos(owner_user_id) WHERE owner_user_id IS NOT NULL;
COMMIT;
