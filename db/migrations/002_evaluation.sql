-- Migration 002: Evaluation Features
-- Adds scorecard templates, rubrics, flags, consensus, culture scoring

-- 1. Scorecard Templates (per role type, seeded with defaults)
CREATE TABLE IF NOT EXISTS scorecard_templates (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    role_type TEXT NOT NULL,
    dimensions JSONB NOT NULL DEFAULT '[]',
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 2. Evaluation Rubrics (per position, auto-generated from JD)
CREATE TABLE IF NOT EXISTS evaluation_rubrics (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    dimension TEXT NOT NULL,
    description TEXT,
    score_1_label TEXT DEFAULT 'Poor',
    score_2_label TEXT DEFAULT 'Below Average',
    score_3_label TEXT DEFAULT 'Adequate',
    score_4_label TEXT DEFAULT 'Good',
    score_5_label TEXT DEFAULT 'Excellent',
    weight DECIMAL DEFAULT 1.0,
    category TEXT DEFAULT 'technical',
    source_template_id INTEGER REFERENCES scorecard_templates(id),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rubrics_position ON evaluation_rubrics(position_id);

-- 3. Candidate Flags (red/green/amber, auto-generated during scoring)
CREATE TABLE IF NOT EXISTS candidate_flags (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    flag_type TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    auto_generated BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_flags_pos_cand ON candidate_flags(position_id, candidate_id);

-- 4. Evaluation Consensus (auto-computed after scorecard submissions)
CREATE TABLE IF NOT EXISTS evaluation_consensus (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    avg_overall DECIMAL,
    avg_per_dimension JSONB DEFAULT '{}',
    evaluator_count INTEGER DEFAULT 0,
    agreement_level TEXT,
    lone_dissent_flag BOOLEAN DEFAULT FALSE,
    recommendation_distribution JSONB DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(position_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_consensus_pos ON evaluation_consensus(position_id);

-- 5. Add culture score to position_candidates
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS match_score_culture DECIMAL;

-- 6. Add culture values config to positions
ALTER TABLE positions ADD COLUMN IF NOT EXISTS culture_values JSONB DEFAULT '[]';

-- 7. Seed default scorecard templates
INSERT INTO scorecard_templates (name, role_type, dimensions, is_default) VALUES
(
    'Engineering',
    'engineering',
    '[{"dimension": "Problem Solving", "weight": 1.0, "description": "Ability to break down complex problems and design efficient solutions", "category": "technical"},
      {"dimension": "System Design", "weight": 1.0, "description": "Architecture thinking, scalability, trade-off analysis", "category": "technical"},
      {"dimension": "Code Quality", "weight": 1.0, "description": "Clean code, testing practices, maintainability", "category": "technical"},
      {"dimension": "Technical Depth", "weight": 1.0, "description": "Deep knowledge in relevant technologies and frameworks", "category": "technical"},
      {"dimension": "Communication", "weight": 0.8, "description": "Clarity in explaining technical concepts", "category": "behavioral"},
      {"dimension": "Collaboration", "weight": 0.8, "description": "Team player, cross-functional effectiveness", "category": "behavioral"}]'::jsonb,
    TRUE
),
(
    'Sales',
    'sales',
    '[{"dimension": "Consultative Selling", "weight": 1.0, "description": "Discovery, needs analysis, solution mapping", "category": "technical"},
      {"dimension": "Pipeline Management", "weight": 1.0, "description": "Forecasting accuracy, deal progression discipline", "category": "technical"},
      {"dimension": "Objection Handling", "weight": 1.0, "description": "Reframing concerns, competitive positioning", "category": "technical"},
      {"dimension": "Industry Knowledge", "weight": 0.8, "description": "Market awareness, competitive landscape understanding", "category": "technical"},
      {"dimension": "Communication", "weight": 1.0, "description": "Presentation skills, storytelling, persuasion", "category": "behavioral"},
      {"dimension": "Drive & Resilience", "weight": 0.8, "description": "Self-motivation, persistence, quota attainment history", "category": "behavioral"}]'::jsonb,
    TRUE
),
(
    'Design',
    'design',
    '[{"dimension": "Visual Design", "weight": 1.0, "description": "Aesthetics, typography, color theory, layout", "category": "technical"},
      {"dimension": "UX Thinking", "weight": 1.0, "description": "User research, information architecture, usability", "category": "technical"},
      {"dimension": "Prototyping", "weight": 0.8, "description": "Figma/Sketch proficiency, interaction design", "category": "technical"},
      {"dimension": "Design Systems", "weight": 0.8, "description": "Component thinking, consistency, documentation", "category": "technical"},
      {"dimension": "Collaboration", "weight": 1.0, "description": "Cross-functional partnership, feedback incorporation", "category": "behavioral"},
      {"dimension": "Storytelling", "weight": 0.8, "description": "Design rationale, presentation to stakeholders", "category": "behavioral"}]'::jsonb,
    TRUE
),
(
    'Product',
    'product',
    '[{"dimension": "Product Strategy", "weight": 1.0, "description": "Vision, roadmap, prioritization frameworks", "category": "technical"},
      {"dimension": "Data-Driven Decisions", "weight": 1.0, "description": "Metrics definition, A/B testing, analytics interpretation", "category": "technical"},
      {"dimension": "Technical Acumen", "weight": 0.8, "description": "Engineering trade-off understanding, API literacy", "category": "technical"},
      {"dimension": "User Empathy", "weight": 1.0, "description": "Customer research, persona development, journey mapping", "category": "behavioral"},
      {"dimension": "Stakeholder Management", "weight": 1.0, "description": "Alignment across engineering, design, business", "category": "behavioral"},
      {"dimension": "Communication", "weight": 0.8, "description": "PRDs, presentations, cross-team updates", "category": "behavioral"}]'::jsonb,
    TRUE
),
(
    'Marketing',
    'marketing',
    '[{"dimension": "Campaign Strategy", "weight": 1.0, "description": "Channel selection, audience targeting, budget allocation", "category": "technical"},
      {"dimension": "Content & Messaging", "weight": 1.0, "description": "Copywriting, brand voice, narrative building", "category": "technical"},
      {"dimension": "Analytics & Attribution", "weight": 1.0, "description": "ROI measurement, funnel analysis, tool proficiency", "category": "technical"},
      {"dimension": "Market Research", "weight": 0.8, "description": "Competitive analysis, trend spotting, customer insights", "category": "technical"},
      {"dimension": "Creativity", "weight": 1.0, "description": "Innovative campaigns, out-of-box thinking", "category": "behavioral"},
      {"dimension": "Cross-Team Collaboration", "weight": 0.8, "description": "Sales alignment, product partnership", "category": "behavioral"}]'::jsonb,
    TRUE
),
(
    'General',
    'general',
    '[{"dimension": "Role-Specific Skills", "weight": 1.0, "description": "Core competencies for the specific role", "category": "technical"},
      {"dimension": "Problem Solving", "weight": 1.0, "description": "Analytical thinking, structured approach to challenges", "category": "technical"},
      {"dimension": "Communication", "weight": 1.0, "description": "Written and verbal clarity, active listening", "category": "behavioral"},
      {"dimension": "Collaboration", "weight": 1.0, "description": "Team effectiveness, conflict resolution", "category": "behavioral"},
      {"dimension": "Ownership", "weight": 0.8, "description": "Initiative, accountability, follow-through", "category": "behavioral"},
      {"dimension": "Growth Mindset", "weight": 0.8, "description": "Learning orientation, feedback receptivity, adaptability", "category": "behavioral"}]'::jsonb,
    TRUE
)
ON CONFLICT DO NOTHING;
