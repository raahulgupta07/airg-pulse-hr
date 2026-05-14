-- 038: Default sector_id for users
ALTER TABLE users ALTER COLUMN sector_id SET DEFAULT 1;
UPDATE users SET sector_id = 1 WHERE sector_id IS NULL;
