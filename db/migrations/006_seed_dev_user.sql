-- 006: seed default dev user (id=1) used by DEV_MODE bypass

INSERT INTO users (id, email, display_name, role, password_hash)
VALUES (1, 'dev@hire.local', 'Dev User', 'admin', '')
ON CONFLICT (id) DO NOTHING;

SELECT setval('users_id_seq', GREATEST((SELECT MAX(id) FROM users), 1));
