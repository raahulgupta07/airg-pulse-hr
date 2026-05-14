-- Demographic fields extracted from CVs (esp. handwritten forms via Vision verifier).
-- dob is stored as text because verifier may return non-ISO formats like "14.5.1994".
ALTER TABLE candidates
  ADD COLUMN IF NOT EXISTS dob            text,
  ADD COLUMN IF NOT EXISTS national_id    text,
  ADD COLUMN IF NOT EXISTS gender         text,
  ADD COLUMN IF NOT EXISTS marital_status text,
  ADD COLUMN IF NOT EXISTS nationality    text,
  ADD COLUMN IF NOT EXISTS religion       text,
  ADD COLUMN IF NOT EXISTS height         text,
  ADD COLUMN IF NOT EXISTS weight         text,
  ADD COLUMN IF NOT EXISTS father_name    text;
