CREATE TABLE IF NOT EXISTS email_templates (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  subject TEXT,
  body TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS offer_templates (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  body TEXT,
  variables JSONB DEFAULT '{}',
  created_by INTEGER REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Seed 4 default email templates
INSERT INTO email_templates (name, subject, body) VALUES
  ('Interview invite', 'Interview invitation — {{position.title}}', 'Hi {{candidate.name}},\n\nWe would like to invite you to an interview for {{position.title}}.\n\nBest,\n{{interviewer}}'),
  ('Rejection - polite', 'Update on your application', 'Hi {{candidate.name}},\n\nThank you for applying to {{position.title}}. We have decided to move forward with other candidates.\n\nWishing you the best,\n{{org}}'),
  ('Offer - generic', 'Offer of employment — {{position.title}}', 'Hi {{candidate.name}},\n\nWe are pleased to offer you the {{position.title}} role.\n\nDetails to follow.\n\n{{org}}'),
  ('Follow-up nudge', 'Quick check-in on your application', 'Hi {{candidate.name}},\n\nJust following up on your application for {{position.title}}. Let us know if you have any questions.\n\n{{org}}')
ON CONFLICT DO NOTHING;

-- Seed 2 default offer templates
INSERT INTO offer_templates (name, body) VALUES
  ('Standard full-time', '## Offer Letter\n\nDear {{candidate.name}},\n\nWe are pleased to offer you the position of {{position.title}}.\n\n**Salary:** {{salary.amount}} {{salary.currency}} per year\n**Start date:** {{start.date}}\n**Benefits:** {{benefits}}\n\nWelcome aboard,\n{{org}}'),
  ('Executive package', '## Executive Offer\n\nDear {{candidate.name}},\n\nWe are delighted to extend an executive offer for {{position.title}}.\n\n**Base salary:** {{salary.amount}} {{salary.currency}}\n**Start date:** {{start.date}}\n**Equity & benefits:** {{benefits}}\n\nLooking forward,\n{{org}}')
ON CONFLICT DO NOTHING;
