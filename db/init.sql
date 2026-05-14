-- ============================================================================
-- HIRE — Database Schema
-- PostgreSQL 18 + PgVector
-- ============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================================
-- USERS & AUTH
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'recruiter',
    -- roles: admin, hiring_manager, recruiter, interviewer, viewer
    avatar_url TEXT,
    department TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    email TEXT,
    expiry BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_tokens_expiry ON auth_tokens(expiry);

-- ============================================================================
-- CENTRAL CV REPOSITORY
-- ============================================================================

CREATE TABLE IF NOT EXISTS candidates (
    id SERIAL PRIMARY KEY,
    -- Personal info
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    location TEXT,
    linkedin_url TEXT,
    -- Current position
    "current_role" TEXT,
    "current_company" TEXT,
    total_experience_years DECIMAL,
    seniority_level TEXT,
    -- Structured extraction
    skills_technical TEXT[] DEFAULT '{}',
    skills_soft TEXT[] DEFAULT '{}',
    tools TEXT[] DEFAULT '{}',
    languages TEXT[] DEFAULT '{}',
    experience JSONB DEFAULT '[]',
    -- [{company, role, start_date, end_date, duration_months, description, location}]
    education JSONB DEFAULT '[]',
    -- [{institution, degree, field, year, gpa}]
    certifications JSONB DEFAULT '[]',
    -- [{name, issuer, year, expiry}]
    projects JSONB DEFAULT '[]',
    -- [{name, description, tech_stack[], url}]
    -- Summaries
    summary_short TEXT,
    summary_detailed TEXT,
    raw_text TEXT,
    -- File info
    pdf_path TEXT,
    file_type TEXT,
    file_name TEXT,
    page_count INTEGER DEFAULT 0,
    -- Quality & tags
    quality_score INTEGER DEFAULT 0,
    -- 0-100 completeness
    tags TEXT[] DEFAULT '{}',
    -- auto-tagged: domain, tech stack, industry
    source TEXT DEFAULT 'upload',
    -- upload, linkedin, referral, bulk
    -- Status
    status TEXT DEFAULT 'active',
    -- active, archived, blacklisted
    -- Processing
    is_processed BOOLEAN DEFAULT FALSE,
    processing_error TEXT,
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_skills ON candidates USING GIN(skills_technical);
CREATE INDEX IF NOT EXISTS idx_candidates_tags ON candidates USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_candidates_name_trgm ON candidates USING GIN(name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_candidates_seniority ON candidates(seniority_level);

-- ============================================================================
-- CANDIDATE EMBEDDINGS (PgVector)
-- ============================================================================

CREATE TABLE IF NOT EXISTS candidate_embeddings (
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    chunk_type TEXT NOT NULL,
    -- 'full_cv', 'skills', 'experience', 'education', 'hype_qa', 'contextual'
    content TEXT,
    metadata JSONB DEFAULT '{}',
    embedding vector(1536),
    quality DECIMAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cand_embed_candidate ON candidate_embeddings(candidate_id);
CREATE INDEX IF NOT EXISTS idx_cand_embed_type ON candidate_embeddings(chunk_type);
CREATE INDEX IF NOT EXISTS idx_cand_embed_vector ON candidate_embeddings
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- ============================================================================
-- CANDIDATE SCREENSHOTS (CV page images)
-- ============================================================================

CREATE TABLE IF NOT EXISTS candidate_screenshots (
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    img_index INTEGER DEFAULT 0,
    path TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- CANDIDATE Q&A PAIRS (HyPE embeddings)
-- ============================================================================

CREATE TABLE IF NOT EXISTS candidate_qa_pairs (
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    embedding vector(1536),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cand_qa_candidate ON candidate_qa_pairs(candidate_id);
CREATE INDEX IF NOT EXISTS idx_cand_qa_vector ON candidate_qa_pairs
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- ============================================================================
-- POSITIONS (Job openings / Projects)
-- ============================================================================

CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    department TEXT,
    location TEXT,
    employment_type TEXT DEFAULT 'full-time',
    -- full-time, part-time, contract, intern
    hiring_manager_id INTEGER REFERENCES users(id),
    -- Status
    status TEXT DEFAULT 'active',
    -- draft, active, paused, closed, filled
    icon TEXT DEFAULT '💼',
    -- JD content
    jd_text TEXT,
    jd_html TEXT,
    jd_enhanced BOOLEAN DEFAULT FALSE,
    jd_embedding vector(1536),
    -- Extracted requirements
    required_skills TEXT[] DEFAULT '{}',
    nice_to_have_skills TEXT[] DEFAULT '{}',
    min_experience_years INTEGER DEFAULT 0,
    education_level TEXT,
    -- preferred, required, none
    industry_keywords TEXT[] DEFAULT '{}',
    required_certifications TEXT[] DEFAULT '{}',
    -- Scoring weights (must sum to 100)
    weight_skills INTEGER DEFAULT 40,
    weight_experience INTEGER DEFAULT 25,
    weight_education INTEGER DEFAULT 10,
    weight_certifications INTEGER DEFAULT 10,
    weight_industry INTEGER DEFAULT 15,
    -- Thresholds
    min_match_score INTEGER DEFAULT 50,
    knockout_criteria JSONB DEFAULT '[]',
    -- [{dimension, min_score}]
    -- Compliance
    dei_score INTEGER,
    legal_check BOOLEAN,
    completeness_score INTEGER,
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_slug ON positions(slug);
CREATE INDEX IF NOT EXISTS idx_positions_skills ON positions USING GIN(required_skills);

-- ============================================================================
-- POSITION MEMBERS (team access)
-- ============================================================================

CREATE TABLE IF NOT EXISTS position_members (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT DEFAULT 'viewer',
    -- admin, hiring_manager, recruiter, interviewer, viewer
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(position_id, user_id)
);

-- ============================================================================
-- POSITION CANDIDATES (junction table with scores)
-- ============================================================================

CREATE TABLE IF NOT EXISTS position_candidates (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    -- Composite score
    match_score_composite DECIMAL,
    -- Per-dimension scores (0-100)
    match_score_skills DECIMAL,
    match_score_experience DECIMAL,
    match_score_education DECIMAL,
    match_score_certifications DECIMAL,
    match_score_industry DECIMAL,
    match_score_semantic DECIMAL,
    -- raw vector similarity
    -- Explanation
    match_explanation TEXT,
    -- LLM-generated "why this candidate fits"
    skills_matched TEXT[] DEFAULT '{}',
    skills_missing TEXT[] DEFAULT '{}',
    -- Pipeline stage
    stage TEXT DEFAULT 'uploaded',
    -- uploaded, screened, shortlisted, interview_scheduled, interviewed, offered, hired, rejected
    stage_changed_at TIMESTAMP,
    rejection_reason TEXT,
    -- Notes & metadata
    notes TEXT,
    interview_date TIMESTAMP,
    interviewer_id INTEGER REFERENCES users(id),
    added_by TEXT DEFAULT 'manual',
    -- 'ai_scan', 'manual', 'bulk_upload'
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(position_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_pos_cand_position ON position_candidates(position_id);
CREATE INDEX IF NOT EXISTS idx_pos_cand_candidate ON position_candidates(candidate_id);
CREATE INDEX IF NOT EXISTS idx_pos_cand_stage ON position_candidates(stage);
CREATE INDEX IF NOT EXISTS idx_pos_cand_score ON position_candidates(match_score_composite DESC NULLS LAST);

-- match_source: distinguishes how a candidate landed on a position (manual upload, ai_scan, bulk, etc.)
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS match_source TEXT DEFAULT 'manual';

-- ============================================================================
-- POSITION AI SCANS (auto-scan tracking; mig 041 + 042)
-- ============================================================================

CREATE TABLE IF NOT EXISTS position_ai_scans (
    id SERIAL PRIMARY KEY,
    position_id INT NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    n_scored INT DEFAULT 0,
    n_matched INT DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pas_position ON position_ai_scans(position_id, created_at DESC);

-- Partial unique index: only one queued/running scan allowed at a time per position.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_pas_active
    ON position_ai_scans(position_id)
    WHERE status IN ('queued', 'running');

-- ============================================================================
-- TEMPLATES
-- ============================================================================

CREATE TABLE IF NOT EXISTS templates (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    -- offer_letter, rejection_email, interview_invite, interview_scorecard, onboarding_checklist, custom
    content TEXT NOT NULL,
    -- Template with {variable} placeholders
    variables JSONB DEFAULT '[]',
    -- [{name, description, required, default_value}]
    tone TEXT DEFAULT 'formal',
    -- formal, friendly, empathetic, corporate
    usage_count INTEGER DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- GENERATED DOCUMENTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS generated_documents (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES templates(id),
    position_id INTEGER REFERENCES positions(id),
    candidate_id INTEGER REFERENCES candidates(id),
    title TEXT,
    content TEXT NOT NULL,
    variables_used JSONB DEFAULT '{}',
    status TEXT DEFAULT 'draft',
    -- draft, ready, sent, archived
    format TEXT DEFAULT 'markdown',
    -- markdown, pdf, docx, email
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gen_docs_position ON generated_documents(position_id);

-- ============================================================================
-- HR BRAIN KNOWLEDGE
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr_brain (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    -- glossary, formula, policy, org_structure, rule, pattern, skill_taxonomy
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    source TEXT DEFAULT 'admin',
    -- admin, agent, auto_learned
    position_id INTEGER REFERENCES positions(id),
    -- NULL = global, else position-scoped
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hr_brain_category ON hr_brain(category);

-- ============================================================================
-- HR BRAIN LEARNINGS (feedback DO/AVOID patterns)
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr_brain_learnings (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    -- learned_positive (DO), learned_negative (AVOID)
    pattern TEXT NOT NULL,
    context TEXT,
    position_id INTEGER REFERENCES positions(id),
    -- NULL = global
    confidence DECIMAL DEFAULT 0.5,
    source_agent TEXT,
    evidence_count INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- CHAT SESSIONS & MESSAGES
-- ============================================================================

CREATE TABLE IF NOT EXISTS chat_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    position_id INTEGER REFERENCES positions(id),
    -- NULL = global HR Brain
    title TEXT,
    message_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_position ON chat_sessions(position_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    -- user, assistant
    content TEXT NOT NULL,
    sources JSONB DEFAULT '[]',
    -- [{candidate_id, name, page, relevance}]
    suggestions TEXT[] DEFAULT '{}',
    -- follow-up question suggestions
    model_used TEXT,
    quality_score INTEGER,
    feedback TEXT,
    -- thumbs_up, thumbs_down, null
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);

-- ============================================================================
-- CONTENT (News & Internal content)
-- ============================================================================

CREATE TABLE IF NOT EXISTS content (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    -- news, policy, announcement, newsletter, custom
    title TEXT NOT NULL,
    body TEXT,
    tone TEXT DEFAULT 'professional',
    format TEXT DEFAULT 'markdown',
    -- markdown, email, slack, pdf
    audience TEXT DEFAULT 'all_employees',
    bullet_points TEXT[] DEFAULT '{}',
    status TEXT DEFAULT 'draft',
    -- draft, published, archived
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    published_at TIMESTAMP
);

-- ============================================================================
-- AUDIT LOG
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    -- candidate_uploaded, position_created, jd_generated, scan_triggered, etc.
    resource_type TEXT,
    -- candidate, position, template, chat
    resource_id INTEGER,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);

-- ============================================================================
-- CANDIDATE NOTES
-- ============================================================================

CREATE TABLE IF NOT EXISTS candidate_notes (
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    note_type TEXT DEFAULT 'general',
    -- general, interview, screening, internal
    position_id INTEGER REFERENCES positions(id),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_candidate_notes_candidate ON candidate_notes(candidate_id);

-- ============================================================================
-- CANDIDATE ACTIVITY TIMELINE
-- ============================================================================

CREATE TABLE IF NOT EXISTS candidate_activity (
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    position_id INTEGER REFERENCES positions(id),
    user_id INTEGER REFERENCES users(id),
    activity_type TEXT NOT NULL,
    -- stage_change, interview_scheduled, interview_completed, scorecard_submitted,
    -- note_added, added_to_position, email_sent, screening_completed
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_candidate_activity_candidate ON candidate_activity(candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_activity_type ON candidate_activity(activity_type);

-- ============================================================================
-- INTERVIEWS
-- ============================================================================

CREATE TABLE IF NOT EXISTS interviews (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    interviewer_id INTEGER REFERENCES users(id),
    interview_type TEXT NOT NULL DEFAULT 'screening',
    -- screening, technical, behavioral, culture_fit, final, panel
    scheduled_at TIMESTAMP NOT NULL,
    duration_minutes INTEGER DEFAULT 60,
    location TEXT,
    meeting_link TEXT,
    status TEXT DEFAULT 'scheduled',
    -- scheduled, confirmed, in_progress, completed, cancelled, no_show
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interviews_position ON interviews(position_id);
CREATE INDEX IF NOT EXISTS idx_interviews_candidate ON interviews(candidate_id);
CREATE INDEX IF NOT EXISTS idx_interviews_scheduled ON interviews(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_interviews_status ON interviews(status);

-- ============================================================================
-- INTERVIEW SCORECARDS
-- ============================================================================

CREATE TABLE IF NOT EXISTS interview_scorecards (
    id SERIAL PRIMARY KEY,
    interview_id INTEGER NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    interviewer_id INTEGER REFERENCES users(id),
    overall_score DECIMAL,
    recommendation TEXT,
    -- strong_hire, hire, no_hire, strong_no_hire
    strengths TEXT,
    concerns TEXT,
    summary TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scorecards_interview ON interview_scorecards(interview_id);

CREATE TABLE IF NOT EXISTS scorecard_scores (
    id SERIAL PRIMARY KEY,
    scorecard_id INTEGER NOT NULL REFERENCES interview_scorecards(id) ON DELETE CASCADE,
    dimension TEXT NOT NULL,
    score DECIMAL NOT NULL,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_scorecard_scores_scorecard ON scorecard_scores(scorecard_id);

-- ============================================================================
-- SCREENING QUESTIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS screening_questions (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    question_type TEXT DEFAULT 'text',
    -- text, yes_no, multiple_choice, number
    options JSONB,
    -- for multiple_choice: ["option1", "option2", ...]
    is_required BOOLEAN DEFAULT TRUE,
    is_knockout BOOLEAN DEFAULT FALSE,
    knockout_answer TEXT,
    sort_order INTEGER DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screening_questions_position ON screening_questions(position_id);

-- ============================================================================
-- SCREENING ANSWERS
-- ============================================================================

CREATE TABLE IF NOT EXISTS screening_answers (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES screening_questions(id) ON DELETE CASCADE,
    answer TEXT,
    submitted_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(position_id, candidate_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_screening_answers_position ON screening_answers(position_id);
CREATE INDEX IF NOT EXISTS idx_screening_answers_candidate ON screening_answers(candidate_id);

-- ============================================================================
-- EVALUATION: SCORECARD TEMPLATES
-- ============================================================================

CREATE TABLE IF NOT EXISTS scorecard_templates (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    role_type TEXT NOT NULL,
    dimensions JSONB NOT NULL DEFAULT '[]',
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- EVALUATION: RUBRICS (per position)
-- ============================================================================

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

-- ============================================================================
-- EVALUATION: CANDIDATE FLAGS (auto-generated)
-- ============================================================================

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

-- ============================================================================
-- EVALUATION: CONSENSUS (auto-computed)
-- ============================================================================

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

-- Add culture score to position_candidates
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS match_score_culture DECIMAL;

-- Add culture values to positions
ALTER TABLE positions ADD COLUMN IF NOT EXISTS culture_values JSONB DEFAULT '[]';

-- ============================================================================
-- EMAIL LOG
-- ============================================================================

CREATE TABLE IF NOT EXISTS email_log (
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
    position_id INTEGER REFERENCES positions(id) ON DELETE SET NULL,
    template_id INTEGER REFERENCES templates(id) ON DELETE SET NULL,
    recipient_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT,
    status TEXT DEFAULT 'pending',
    -- pending, sent, failed, skipped
    sent_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_log_candidate ON email_log(candidate_id);
CREATE INDEX IF NOT EXISTS idx_email_log_position ON email_log(position_id);

-- ============================================================================
-- SEARCH TEXT (full-text search support)
-- ============================================================================

-- Add full-text search vector to candidates
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE OR REPLACE FUNCTION candidates_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english',
        coalesce(NEW.name, '') || ' ' ||
        coalesce(NEW."current_role", '') || ' ' ||
        coalesce(NEW."current_company", '') || ' ' ||
        coalesce(NEW.summary_short, '') || ' ' ||
        coalesce(array_to_string(NEW.skills_technical, ' '), '') || ' ' ||
        coalesce(array_to_string(NEW.tags, ' '), '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_candidates_search ON candidates;
CREATE TRIGGER trg_candidates_search
    BEFORE INSERT OR UPDATE ON candidates
    FOR EACH ROW EXECUTE FUNCTION candidates_search_vector_update();

CREATE INDEX IF NOT EXISTS idx_candidates_search ON candidates USING GIN(search_vector);

-- ============================================================================
-- SEED DATA
-- ============================================================================

-- Create admin via: POST /api/auth/register

-- Default templates
INSERT INTO templates (name, category, content, variables, tone) VALUES
(
    'Standard Offer Letter',
    'offer_letter',
    E'Dear {candidate_name},\n\nWe are pleased to offer you the position of {role} at {company_name}.\n\n**Start Date:** {start_date}\n**Compensation:** {salary}\n**Reporting To:** {manager_name}\n\nThis offer is contingent upon successful completion of background verification.\n\nPlease confirm your acceptance by {deadline}.\n\nWelcome aboard!\n\nBest regards,\n{sender_name}\n{sender_title}',
    '[{"name": "candidate_name", "required": true}, {"name": "role", "required": true}, {"name": "company_name", "required": true}, {"name": "start_date", "required": true}, {"name": "salary", "required": true}, {"name": "manager_name", "required": true}, {"name": "deadline", "required": true}, {"name": "sender_name", "required": true}, {"name": "sender_title", "required": true}]',
    'formal'
),
(
    'Post-Interview Rejection',
    'rejection_email',
    E'Dear {candidate_name},\n\nThank you for taking the time to interview for the {role} position at {company_name}.\n\nAfter careful consideration, we have decided to move forward with another candidate whose experience more closely aligns with our current needs.\n\nThis was a difficult decision as your qualifications were impressive. We encourage you to apply for future openings.\n\nWe wish you all the best in your career.\n\nKind regards,\n{sender_name}',
    '[{"name": "candidate_name", "required": true}, {"name": "role", "required": true}, {"name": "company_name", "required": true}, {"name": "sender_name", "required": true}]',
    'empathetic'
),
(
    'Interview Invite',
    'interview_invite',
    E'Dear {candidate_name},\n\nWe were impressed by your application for the {role} position and would like to invite you for an interview.\n\n**Date:** {interview_date}\n**Time:** {interview_time}\n**Format:** {interview_format}\n**Interviewer:** {interviewer_name}\n\n{additional_instructions}\n\nPlease confirm your availability.\n\nBest regards,\n{sender_name}',
    '[{"name": "candidate_name", "required": true}, {"name": "role", "required": true}, {"name": "interview_date", "required": true}, {"name": "interview_time", "required": true}, {"name": "interview_format", "required": true}, {"name": "interviewer_name", "required": true}, {"name": "additional_instructions", "required": false}, {"name": "sender_name", "required": true}]',
    'professional'
),
(
    'Technical Interview Scorecard',
    'interview_scorecard',
    E'# Interview Scorecard — {candidate_name}\n**Position:** {role}\n**Interviewer:** {interviewer_name}\n**Date:** {interview_date}\n\n## Technical Assessment\n| Dimension | Score (1-5) | Notes |\n|---|---|---|\n| Problem Solving | __ | |\n| System Design | __ | |\n| Coding Quality | __ | |\n| Domain Knowledge | __ | |\n| Communication | __ | |\n\n## Culture Fit\n| Dimension | Score (1-5) | Notes |\n|---|---|---|\n| Collaboration | __ | |\n| Ownership | __ | |\n| Growth Mindset | __ | |\n\n## Overall Assessment\n- **Recommendation:** [ ] Strong Hire  [ ] Hire  [ ] No Hire  [ ] Strong No Hire\n- **Summary:**\n\n',
    '[{"name": "candidate_name", "required": true}, {"name": "role", "required": true}, {"name": "interviewer_name", "required": true}, {"name": "interview_date", "required": true}]',
    'professional'
)
ON CONFLICT DO NOTHING;

-- Default scorecard templates
INSERT INTO scorecard_templates (name, role_type, dimensions, is_default) VALUES
('Engineering', 'engineering', '[{"dimension":"Problem Solving","weight":1.0,"description":"Break down complex problems","category":"technical"},{"dimension":"System Design","weight":1.0,"description":"Architecture and scalability","category":"technical"},{"dimension":"Code Quality","weight":1.0,"description":"Clean code and testing","category":"technical"},{"dimension":"Technical Depth","weight":1.0,"description":"Deep technology knowledge","category":"technical"},{"dimension":"Communication","weight":0.8,"description":"Explain technical concepts","category":"behavioral"},{"dimension":"Collaboration","weight":0.8,"description":"Team effectiveness","category":"behavioral"}]'::jsonb, TRUE),
('Sales', 'sales', '[{"dimension":"Consultative Selling","weight":1.0,"description":"Discovery and needs analysis","category":"technical"},{"dimension":"Pipeline Management","weight":1.0,"description":"Forecasting and deal progression","category":"technical"},{"dimension":"Objection Handling","weight":1.0,"description":"Reframing concerns","category":"technical"},{"dimension":"Industry Knowledge","weight":0.8,"description":"Market awareness","category":"technical"},{"dimension":"Communication","weight":1.0,"description":"Presentation and persuasion","category":"behavioral"},{"dimension":"Drive & Resilience","weight":0.8,"description":"Self-motivation and persistence","category":"behavioral"}]'::jsonb, TRUE),
('Design', 'design', '[{"dimension":"Visual Design","weight":1.0,"description":"Aesthetics and layout","category":"technical"},{"dimension":"UX Thinking","weight":1.0,"description":"User research and usability","category":"technical"},{"dimension":"Prototyping","weight":0.8,"description":"Figma/Sketch proficiency","category":"technical"},{"dimension":"Design Systems","weight":0.8,"description":"Component thinking","category":"technical"},{"dimension":"Collaboration","weight":1.0,"description":"Cross-functional partnership","category":"behavioral"},{"dimension":"Storytelling","weight":0.8,"description":"Design rationale","category":"behavioral"}]'::jsonb, TRUE),
('Product', 'product', '[{"dimension":"Product Strategy","weight":1.0,"description":"Vision and prioritization","category":"technical"},{"dimension":"Data-Driven Decisions","weight":1.0,"description":"Metrics and A/B testing","category":"technical"},{"dimension":"Technical Acumen","weight":0.8,"description":"Engineering trade-offs","category":"technical"},{"dimension":"User Empathy","weight":1.0,"description":"Customer research","category":"behavioral"},{"dimension":"Stakeholder Management","weight":1.0,"description":"Cross-team alignment","category":"behavioral"},{"dimension":"Communication","weight":0.8,"description":"PRDs and presentations","category":"behavioral"}]'::jsonb, TRUE),
('Marketing', 'marketing', '[{"dimension":"Campaign Strategy","weight":1.0,"description":"Channel and targeting","category":"technical"},{"dimension":"Content & Messaging","weight":1.0,"description":"Copywriting and brand voice","category":"technical"},{"dimension":"Analytics & Attribution","weight":1.0,"description":"ROI measurement","category":"technical"},{"dimension":"Market Research","weight":0.8,"description":"Competitive analysis","category":"technical"},{"dimension":"Creativity","weight":1.0,"description":"Innovative campaigns","category":"behavioral"},{"dimension":"Cross-Team Collaboration","weight":0.8,"description":"Sales and product alignment","category":"behavioral"}]'::jsonb, TRUE),
('General', 'general', '[{"dimension":"Role-Specific Skills","weight":1.0,"description":"Core competencies","category":"technical"},{"dimension":"Problem Solving","weight":1.0,"description":"Analytical thinking","category":"technical"},{"dimension":"Communication","weight":1.0,"description":"Written and verbal clarity","category":"behavioral"},{"dimension":"Collaboration","weight":1.0,"description":"Team effectiveness","category":"behavioral"},{"dimension":"Ownership","weight":0.8,"description":"Initiative and accountability","category":"behavioral"},{"dimension":"Growth Mindset","weight":0.8,"description":"Learning orientation","category":"behavioral"}]'::jsonb, TRUE)
ON CONFLICT DO NOTHING;
