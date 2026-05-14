CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS competency_frameworks (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS competencies (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT gen_random_uuid() UNIQUE,
    framework_id INT REFERENCES competency_frameworks(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    category TEXT,
    description TEXT,
    level_descriptors JSONB DEFAULT '{}',
    star_questions JSONB DEFAULT '[]',
    related_keys TEXT[] DEFAULT '{}',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (framework_id, key)
);
CREATE INDEX IF NOT EXISTS idx_comp_framework ON competencies(framework_id);
CREATE INDEX IF NOT EXISTS idx_comp_active ON competencies(active);

CREATE TABLE IF NOT EXISTS jd_competencies (
    id SERIAL PRIMARY KEY,
    jd_id INT REFERENCES jd_repository(id) ON DELETE CASCADE,
    competency_id INT REFERENCES competencies(id) ON DELETE CASCADE,
    required_level INT NOT NULL CHECK (required_level BETWEEN 1 AND 5),
    importance TEXT DEFAULT 'required',
    weight NUMERIC DEFAULT 1.0,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(jd_id, competency_id)
);
CREATE INDEX IF NOT EXISTS idx_jd_comp_jd ON jd_competencies(jd_id);

CREATE TABLE IF NOT EXISTS position_competencies (
    id SERIAL PRIMARY KEY,
    position_id INT REFERENCES positions(id) ON DELETE CASCADE,
    competency_id INT REFERENCES competencies(id) ON DELETE CASCADE,
    required_level INT NOT NULL CHECK (required_level BETWEEN 1 AND 5),
    importance TEXT DEFAULT 'required',
    weight NUMERIC DEFAULT 1.0,
    source TEXT DEFAULT 'jd',
    notes TEXT,
    UNIQUE(position_id, competency_id)
);
CREATE INDEX IF NOT EXISTS idx_pos_comp_pos ON position_competencies(position_id);

CREATE TABLE IF NOT EXISTS candidate_competencies (
    id SERIAL PRIMARY KEY,
    candidate_id INT REFERENCES candidates(id) ON DELETE CASCADE,
    competency_id INT REFERENCES competencies(id) ON DELETE CASCADE,
    level NUMERIC,
    source TEXT,
    source_id INT,
    evidence TEXT,
    confidence NUMERIC,
    rated_by INT,
    rated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(candidate_id, competency_id, source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_cand_comp_cid ON candidate_competencies(candidate_id);

ALTER TABLE jd_repository       ADD COLUMN IF NOT EXISTS weight_competencies NUMERIC DEFAULT 0;
ALTER TABLE positions           ADD COLUMN IF NOT EXISTS weight_competencies NUMERIC DEFAULT 0;
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS match_score_competencies NUMERIC;
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS competency_gaps JSONB DEFAULT '[]';

INSERT INTO competency_frameworks (name, description, is_default) VALUES
    ('KF4D', 'Korn Ferry 4 Dimensions baseline', TRUE)
ON CONFLICT (name) DO NOTHING;

INSERT INTO competencies (framework_id, key, label, category, description, level_descriptors, star_questions) VALUES
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'strategic-thinking','Strategic Thinking','Leadership',
     'Sees patterns, sets direction, anticipates downstream impact.',
     '{"1":"reactive","2":"task-focus","3":"team-level","4":"function-level","5":"enterprise multi-year"}',
     '["Tell me about a time you set direction for a team without complete information."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'decision-making','Decision Making','Leadership',
     'Makes timely, well-reasoned calls under pressure.',
     '{"1":"avoids","2":"defers","3":"data-driven","4":"considers tradeoffs","5":"decisive under ambiguity"}',
     '["Walk me through a difficult call when stakeholders disagreed."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'communication','Communication','People',
     'Clear written + verbal; tailors to audience.',
     '{"1":"unclear","2":"basic","3":"competent","4":"persuasive","5":"executive presence"}',
     '["Describe explaining a complex topic to a non-technical exec."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'collaboration','Collaboration','People',
     'Works across teams; resolves conflict.',
     '{"1":"siloed","2":"transactional","3":"team player","4":"cross-functional","5":"alliance-building"}',
     '["Tell me about cross-team work that nearly failed."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'problem-solving','Problem Solving','Delivery',
     'Decomposes ambiguous problems; finds root cause.',
     '{"1":"surface","2":"linear","3":"systematic","4":"first-principles","5":"reframes problem"}',
     '["Describe diagnosing a non-obvious production issue."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'drive-for-results','Drive for Results','Delivery',
     'Owns outcomes; pushes through obstacles.',
     '{"1":"low","2":"reactive","3":"committed","4":"raises bar","5":"sets new bar org-wide"}',
     '["Tell me about a goal everyone said was impossible."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'adaptability','Adaptability','Delivery',
     'Adjusts to change; learns quickly.',
     '{"1":"resistant","2":"slow","3":"open","4":"thrives","5":"drives change in others"}',
     '["Describe pivoting after major direction change."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'coaching-mentoring','Coaching & Mentoring','Leadership',
     'Develops others; gives feedback.',
     '{"1":"none","2":"informal","3":"structured","4":"transforms careers","5":"builds leaders"}',
     '["Tell me about coaching someone through a hard year."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'stakeholder-management','Stakeholder Management','People',
     'Aligns stakeholders; manages up + across.',
     '{"1":"avoids","2":"reactive","3":"proactive","4":"influences","5":"builds coalitions"}',
     '["How did you handle conflicting executive priorities?"]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'technical-leadership','Technical Leadership','Leadership',
     'Sets technical direction; builds engineering culture.',
     '{"1":"individual contributor","2":"team-level","3":"system-level","4":"platform-level","5":"industry-level"}',
     '["Describe a technical bet that paid off — or failed."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'cultural-awareness','Cultural Awareness','People',
     'Operates effectively across cultures.',
     '{"1":"low","2":"basic","3":"adaptive","4":"bridges","5":"global leadership"}',
     '["Tell me about working in a culture very different from yours."]'),
    ((SELECT id FROM competency_frameworks WHERE name='KF4D'),'innovation','Innovation','Delivery',
     'Generates new ideas; experiments; commercialises.',
     '{"1":"none","2":"copies","3":"improves","4":"reframes","5":"creates category"}',
     '["Describe a novel idea you shipped to production."]')
ON CONFLICT (framework_id, key) DO NOTHING;
