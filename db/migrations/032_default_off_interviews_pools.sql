-- Default Interviews + Pools nav OFF. Superadmin can re-enable from
-- Admin → SYSTEM → FEATURES toggles. Only flips rows still at the
-- env-seeded default (updated_by IS NULL) to preserve any explicit
-- admin choice already in place.
UPDATE system_flags
   SET value = 'false'::jsonb,
       updated_at = NOW()
 WHERE key IN ('feature_interviews', 'feature_pools')
   AND updated_by IS NULL;
