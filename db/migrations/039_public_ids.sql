-- 039: Public IDs (dual-id pattern, ULID + prefix)
-- Internal: bigint SERIAL (joins, FKs)
-- External: text public_id (URLs, API, logs)

-- pgcrypto for gen_random_bytes (fallback if no ulid extension)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Crockford base32 ULID generator (26 chars: 10 ts + 16 random)
CREATE OR REPLACE FUNCTION gen_ulid() RETURNS TEXT AS $$
DECLARE
  alphabet TEXT := '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  ts_ms BIGINT;
  rand_bytes BYTEA;
  out TEXT := '';
  v BIGINT;
  i INT;
BEGIN
  ts_ms := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;
  v := ts_ms;
  FOR i IN 1..10 LOOP
    out := substr(alphabet, ((v >> ((10-i)*5)) & 31)::INT + 1, 1) || out;
  END LOOP;
  out := reverse(out);
  rand_bytes := gen_random_bytes(10);
  FOR i IN 0..15 LOOP
    out := out || substr(alphabet, (get_byte(rand_bytes, i/2) >> (CASE WHEN i%2=0 THEN 4 ELSE 0 END) & 15)::INT + 1, 1);
  END LOOP;
  RETURN out;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- Helper: add public_id col + backfill + unique index
DO $$
DECLARE
  t TEXT;
  p TEXT;
  pairs TEXT[][] := ARRAY[
    ['candidates',     'cv'],
    ['jd_repository',  'jd'],
    ['positions',      'pos'],
    ['users',          'usr'],
    ['sectors',        'sec']
  ];
  i INT;
BEGIN
  FOR i IN 1..array_length(pairs, 1) LOOP
    t := pairs[i][1];
    p := pairs[i][2];
    -- skip if table missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = t) THEN
      RAISE NOTICE 'skip %, table missing', t;
      CONTINUE;
    END IF;
    -- add column
    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS public_id TEXT', t);
    -- backfill nulls
    EXECUTE format('UPDATE %I SET public_id = %L || ''_'' || gen_ulid() WHERE public_id IS NULL', t, p);
    -- set NOT NULL + unique
    EXECUTE format('ALTER TABLE %I ALTER COLUMN public_id SET NOT NULL', t);
    EXECUTE format('CREATE UNIQUE INDEX IF NOT EXISTS idx_%s_public_id ON %I(public_id)', t, t);
  END LOOP;
END $$;
