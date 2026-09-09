-- SPDX-License-Identifier: AGPL-3.0-only
CREATE SCHEMA mt;
REVOKE ALL ON SCHEMA mt FROM PUBLIC;
CREATE TABLE mt.schema_version (version integer PRIMARY KEY CHECK (version = 1));
INSERT INTO mt.schema_version VALUES (1);
CREATE TABLE mt.owners (id uuid PRIMARY KEY);
CREATE TABLE mt.archives (id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES mt.owners(id), UNIQUE(id,owner_id));
CREATE TABLE mt.devices (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL, archive_id uuid NOT NULL,
 token_hash text NOT NULL UNIQUE CHECK(length(token_hash)=64), name text NOT NULL,
 revoked boolean NOT NULL DEFAULT false,
 FOREIGN KEY(archive_id,owner_id) REFERENCES mt.archives(id,owner_id)
);
CREATE TABLE mt.invitations (
 token_hash text PRIMARY KEY CHECK(length(token_hash)=64), archive_id uuid NOT NULL REFERENCES mt.archives(id),
 expires_at timestamptz NOT NULL, consumed boolean NOT NULL DEFAULT false
);
CREATE TABLE mt.frames (
 archive_id uuid NOT NULL, id uuid NOT NULL, owner_id uuid NOT NULL,
 registering_device_id uuid NOT NULL REFERENCES mt.devices(id), metadata jsonb NOT NULL,
 committed_at timestamptz, PRIMARY KEY(archive_id,id),
 FOREIGN KEY(archive_id,owner_id) REFERENCES mt.archives(id,owner_id)
);
CREATE TABLE mt.jobs (
 archive_id uuid NOT NULL, frame_id uuid NOT NULL, owner_id uuid NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK (state='pending'),
 PRIMARY KEY(archive_id,frame_id), FOREIGN KEY(archive_id,frame_id) REFERENCES mt.frames(archive_id,id),
 FOREIGN KEY(archive_id,owner_id) REFERENCES mt.archives(id,owner_id)
);
ALTER TABLE mt.owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE mt.archives ENABLE ROW LEVEL SECURITY;
ALTER TABLE mt.frames ENABLE ROW LEVEL SECURITY;
ALTER TABLE mt.jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_scope ON mt.owners USING(id::text = current_setting('mt.owner_id',true));
CREATE POLICY owner_scope ON mt.archives USING(owner_id::text = current_setting('mt.owner_id',true));
CREATE POLICY owner_scope ON mt.frames USING(owner_id::text = current_setting('mt.owner_id',true)) WITH CHECK(owner_id::text = current_setting('mt.owner_id',true));
CREATE POLICY owner_scope ON mt.jobs USING(owner_id::text = current_setting('mt.owner_id',true)) WITH CHECK(owner_id::text = current_setting('mt.owner_id',true));

-- Bootstrap/auth tables are private. Only these fixed-search-path functions may
-- cross scope; runtime has no SELECT on devices/invitations and no admin API.
CREATE FUNCTION mt.authenticate(h text) RETURNS TABLE(owner_id uuid, archive_id uuid, device_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
 SELECT d.owner_id,d.archive_id,d.id FROM mt.devices d WHERE d.token_hash=h AND NOT d.revoked FOR SHARE OF d
$$;
CREATE FUNCTION mt.redeem(h text, new_id uuid, new_hash text, device_name text)
RETURNS TABLE(owner_id uuid, archive_id uuid) LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE a uuid; o uuid;
BEGIN
 SELECT i.archive_id INTO a FROM mt.invitations i
 WHERE i.token_hash=h AND NOT i.consumed AND i.expires_at>clock_timestamp() FOR UPDATE;
 IF a IS NULL THEN RETURN; END IF;
 SELECT ar.owner_id INTO o FROM mt.archives ar WHERE ar.id=a;
 UPDATE mt.invitations SET consumed=true WHERE token_hash=h;
 INSERT INTO mt.devices(id,owner_id,archive_id,token_hash,name) VALUES(new_id,o,a,new_hash,device_name);
 RETURN QUERY SELECT o,a;
END $$;
-- Recovery enumerates owner IDs only, then uses ordinary RLS-scoped transactions.
CREATE FUNCTION mt.recovery_owners() RETURNS SETOF uuid LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
 SELECT id FROM mt.owners ORDER BY id
$$;
CREATE FUNCTION mt.recovery_archive_owner(a uuid) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
 SELECT owner_id FROM mt.archives WHERE id=a
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA mt FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA mt FROM PUBLIC;
