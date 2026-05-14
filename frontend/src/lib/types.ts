export interface Candidate {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  location: string | null;
  current_role: string | null;
  current_company: string | null;
  total_experience_years: number | null;
  seniority_level: string | null;
  skills_technical: string[];
  skills_soft: string[];
  tools: string[];
  languages: string[];
  experience: Experience[];
  education: Education[];
  certifications: Certification[];
  projects: Project[];
  summary_short: string | null;
  summary_detailed: string | null;
  quality_score: number;
  tags: string[];
  source: string;
  status: string;
  is_processed: boolean;
  created_at: string;
}

export interface Experience {
  company: string;
  role: string;
  start_date: string;
  end_date: string;
  duration_months: number;
  description: string;
  location: string;
}

export interface Education {
  institution: string;
  degree: string;
  field: string;
  year: number;
  gpa: string | null;
}

export interface Certification {
  name: string;
  issuer: string;
  year: number;
}

export interface Project {
  name: string;
  description: string;
  tech_stack: string[];
}

export interface Position {
  id: number;
  slug: string;
  title: string;
  department: string;
  location: string;
  employment_type: string;
  status: string;
  icon: string;
  jd_text: string | null;
  required_skills: string[];
  nice_to_have_skills: string[];
  min_experience_years: number;
  weight_skills: number;
  weight_experience: number;
  weight_education: number;
  weight_certifications: number;
  weight_industry: number;
  cv_count: number;
  shortlisted: number;
  avg_match: number | null;
  pipeline: Record<string, number>;
  created_at: string;
}

export interface JD {
  id: number;
  title: string;
  department: string;
  seniority_level: string;
  employment_type: string;
  jd_text: string;
  jd_enhanced: boolean;
  required_skills: string[];
  nice_to_have_skills: string[];
  min_experience_years: number;
  education_level: string;
  industry_keywords: string[];
  dei_score: number | null;
  legal_check: boolean | null;
  completeness_score: number | null;
  tags: string[];
  status: string;
  used_count: number;
  created_at: string;
  updated_at: string;
}

export interface Offer {
  id: number;
  position_id: number;
  candidate_id: number;
  salary_amount: number;
  salary_currency: string;
  salary_period: string;
  equity: string | null;
  bonus: string | null;
  start_date: string | null;
  expiry_date: string | null;
  benefits: string | null;
  status: string;
  candidate_name?: string;
}

export interface ChatMessage {
  id: number;
  session_id: number;
  role: 'user' | 'assistant';
  content: string;
  sources: any[];
  suggestions: string[];
  model_used: string;
  feedback: string | null;
  created_at: string;
}

export interface Notification {
  id: number;
  type: string;
  title: string;
  message: string;
  link: string;
  is_read: boolean;
  created_at: string;
}

// ===========================================================================
// Evaluation Types
// ===========================================================================

export interface EvaluationRubric {
  id: number;
  position_id: number;
  dimension: string;
  description: string;
  score_1_label: string;
  score_2_label: string;
  score_3_label: string;
  score_4_label: string;
  score_5_label: string;
  weight: number;
  category: string;
}

export interface EvaluationConsensus {
  position_id: number;
  candidate_id: number;
  avg_overall: number;
  avg_per_dimension: Record<string, number>;
  evaluator_count: number;
  agreement_level: string;
  lone_dissent_flag: boolean;
  recommendation_distribution: Record<string, number>;
}

export interface CandidateFlag {
  id: number;
  position_id: number;
  candidate_id: number;
  flag_type: 'red' | 'green' | 'amber';
  category: string;
  title: string;
  description: string;
  auto_generated: boolean;
}

export interface VoteDistribution {
  strong_hire: number;
  hire: number;
  no_hire: number;
  strong_no_hire: number;
}

export interface StackRankEntry {
  candidate_id: number;
  rank: number;
  name: string;
  composite: number;
  consensus_avg: number | null;
  culture_score: number | null;
  flag_counts: Record<string, number>;
  flag_penalty: number;
  final_score: number;
  stage: string;
}

export interface ScorecardTemplate {
  id: number;
  name: string;
  role_type: string;
  dimensions: Array<{ dimension: string; weight: number; description: string; category: string }>;
  is_default: boolean;
}

export interface CalibrationEntry {
  interviewer_id: number;
  interviewer_name: string;
  avg_score: number;
  std_dev: number;
  scorecard_count: number;
  harshness_index: number;
  min_score?: number;
  max_score?: number;
}
