CREATE TABLE IF NOT EXISTS cluster_settings (
 id integer PRIMARY KEY CHECK(id=1), mode text NOT NULL CHECK(mode IN ('simulation','live')),
 enabled boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS domains (
 domain text PRIMARY KEY, available_at timestamptz NOT NULL DEFAULT now(),
 lease uuid, lease_until timestamptz NOT NULL DEFAULT '-infinity'
);
CREATE INDEX IF NOT EXISTS domains_available ON domains(available_at,lease_until);
CREATE TABLE IF NOT EXISTS jobs (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, email text NOT NULL UNIQUE,
 domain text NOT NULL, source_id bigint,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','leased','started','done')),
 lease uuid, owner text, lease_until timestamptz,
 started_at timestamptz, finished_at timestamptz, result jsonb, exported_at timestamptz
);
CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(domain,id) WHERE state='pending';
CREATE INDEX IF NOT EXISTS jobs_leased ON jobs(lease_until) WHERE state IN ('leased','started');
CREATE INDEX IF NOT EXISTS jobs_finished ON jobs(finished_at) WHERE state='done';
CREATE TABLE IF NOT EXISTS provider_limits (
 provider text PRIMARY KEY, next_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS control_cache (
 domain text PRIMARY KEY, mx text NOT NULL, verdict text NOT NULL, expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS import_sessions (
 source text PRIMARY KEY, last_id bigint NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now()
);
