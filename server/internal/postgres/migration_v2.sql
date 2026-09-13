-- SPDX-License-Identifier: AGPL-3.0-only
-- Append-only migration: migration.sql remains the original v1 bytes.
-- Block frame INSERT/UPDATE writers until both the backfill and trigger are committed.
LOCK TABLE mt.frames IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE mt.schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE mt.schema_version SET version=2;
ALTER TABLE mt.schema_version ADD CONSTRAINT schema_version_version_check CHECK(version=2);

CREATE TABLE mt.assets (
 archive_id uuid NOT NULL, id uuid NOT NULL, owner_id uuid NOT NULL,
 source_kind text NOT NULL CHECK(source_kind IN ('frame','dataset')),
 frame_id uuid, dataset_name text, dataset_version text, item_id text,
 sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 byte_length bigint NOT NULL CHECK(byte_length BETWEEN 1 AND 16777216),
 observed_at_ms bigint CHECK(observed_at_ms BETWEEN 0 AND 9007199254740991),
 sequence_id text, sequence_position_ms bigint CHECK(sequence_position_ms BETWEEN 0 AND 9007199254740991),
 provenance jsonb,
 PRIMARY KEY(archive_id,id), UNIQUE(archive_id,id,owner_id), UNIQUE(archive_id,frame_id),
 UNIQUE(archive_id,dataset_name,dataset_version,item_id),
 FOREIGN KEY(archive_id,owner_id) REFERENCES mt.archives(id,owner_id),
 FOREIGN KEY(archive_id,frame_id) REFERENCES mt.frames(archive_id,id),
 CHECK((sequence_id IS NULL)=(sequence_position_ms IS NULL)),
 CONSTRAINT dataset_identity_bytes CHECK(source_kind<>'dataset' OR octet_length(dataset_name)+octet_length(dataset_version)+octet_length(item_id)<=1024),
 CHECK((source_kind='frame' AND frame_id IS NOT NULL AND dataset_name IS NULL AND dataset_version IS NULL AND item_id IS NULL AND provenance IS NULL)
 OR (source_kind='dataset' AND frame_id IS NULL AND dataset_name IS NOT NULL AND dataset_version IS NOT NULL AND item_id IS NOT NULL AND provenance IS NOT NULL))
);
CREATE TABLE mt.index_generations (
 archive_id uuid NOT NULL, id text NOT NULL CHECK(id ~ '^[0-9a-f]{64}$'), owner_id uuid NOT NULL,
 model_fingerprint text NOT NULL, policy_fingerprint text NOT NULL,
 dimension integer NOT NULL CHECK(dimension BETWEEN 1 AND 4096),
 mode text NOT NULL CHECK(mode IN ('full','overlap')), description jsonb NOT NULL,
 PRIMARY KEY(archive_id,id), UNIQUE(archive_id,id,owner_id),
 FOREIGN KEY(archive_id,owner_id) REFERENCES mt.archives(id,owner_id)
);
CREATE TABLE mt.index_jobs (
 archive_id uuid NOT NULL, generation_id text NOT NULL, asset_id uuid NOT NULL, owner_id uuid NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','leased','complete','failed')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
 lease_token uuid, lease_until timestamptz, error_code text,
 PRIMARY KEY(archive_id,generation_id,asset_id),
 FOREIGN KEY(archive_id,generation_id,owner_id) REFERENCES mt.index_generations(archive_id,id,owner_id),
 FOREIGN KEY(archive_id,asset_id,owner_id) REFERENCES mt.assets(archive_id,id,owner_id),
 CHECK((state='leased')=(lease_token IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE TABLE mt.regions (
 archive_id uuid NOT NULL, generation_id text NOT NULL, asset_id uuid NOT NULL, owner_id uuid NOT NULL,
 ordinal integer NOT NULL CHECK(ordinal BETWEEN 0 AND 63), kind text NOT NULL CHECK(kind IN ('full','crop')),
 box double precision[] NOT NULL CHECK(cardinality(box)=4 AND box[1]>=0 AND box[2]>=0 AND box[3]<=1 AND box[4]<=1 AND box[1]<box[3] AND box[2]<box[4]),
 embedding real[] NOT NULL CHECK(cardinality(embedding) BETWEEN 1 AND 4096),
 PRIMARY KEY(archive_id,generation_id,asset_id,ordinal),
 FOREIGN KEY(archive_id,generation_id,asset_id) REFERENCES mt.index_jobs(archive_id,generation_id,asset_id),
 FOREIGN KEY(archive_id,generation_id,owner_id) REFERENCES mt.index_generations(archive_id,id,owner_id),
 FOREIGN KEY(archive_id,asset_id,owner_id) REFERENCES mt.assets(archive_id,id,owner_id)
);
CREATE INDEX index_jobs_claim ON mt.index_jobs(archive_id,generation_id,state,asset_id);
ALTER TABLE mt.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE mt.index_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE mt.index_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE mt.regions ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_scope ON mt.assets USING(owner_id::text=current_setting('mt.owner_id',true)) WITH CHECK(owner_id::text=current_setting('mt.owner_id',true));
CREATE POLICY owner_scope ON mt.index_generations USING(owner_id::text=current_setting('mt.owner_id',true)) WITH CHECK(owner_id::text=current_setting('mt.owner_id',true));
CREATE POLICY owner_scope ON mt.index_jobs USING(owner_id::text=current_setting('mt.owner_id',true)) WITH CHECK(owner_id::text=current_setting('mt.owner_id',true));
CREATE POLICY owner_scope ON mt.regions USING(owner_id::text=current_setting('mt.owner_id',true)) WITH CHECK(owner_id::text=current_setting('mt.owner_id',true));

-- Preserve actual request wall time and only session-qualified elapsed time.
INSERT INTO mt.assets(archive_id,id,owner_id,source_kind,frame_id,sha256,byte_length,observed_at_ms,sequence_id,sequence_position_ms)
 SELECT archive_id,gen_random_uuid(),owner_id,'frame',id,metadata->>'sha256',(metadata->>'byte_length')::bigint,
 (metadata->>'request_wall_ms')::bigint,
 CASE WHEN metadata->>'request_elapsed_ms' IS NOT NULL THEN metadata->>'session_id' END,
 CASE WHEN metadata->>'session_id' IS NOT NULL THEN (metadata->>'request_elapsed_ms')::bigint END
 FROM mt.frames WHERE committed_at IS NOT NULL;
CREATE FUNCTION mt.frame_asset() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.committed_at IS NOT NULL THEN
 INSERT INTO mt.assets(archive_id,id,owner_id,source_kind,frame_id,sha256,byte_length,observed_at_ms,sequence_id,sequence_position_ms)
 VALUES(NEW.archive_id,gen_random_uuid(),NEW.owner_id,'frame',NEW.id,NEW.metadata->>'sha256',(NEW.metadata->>'byte_length')::bigint,
 (NEW.metadata->>'request_wall_ms')::bigint,
 CASE WHEN NEW.metadata->>'request_elapsed_ms' IS NOT NULL THEN NEW.metadata->>'session_id' END,
 CASE WHEN NEW.metadata->>'session_id' IS NOT NULL THEN (NEW.metadata->>'request_elapsed_ms')::bigint END) ON CONFLICT(archive_id,frame_id) DO NOTHING;
 END IF; RETURN NEW;
END $$;
CREATE TRIGGER frame_asset AFTER INSERT OR UPDATE OF committed_at ON mt.frames FOR EACH ROW EXECUTE FUNCTION mt.frame_asset();
REVOKE ALL ON mt.assets,mt.index_generations,mt.index_jobs,mt.regions FROM PUBLIC;
REVOKE ALL ON FUNCTION mt.frame_asset() FROM PUBLIC;
