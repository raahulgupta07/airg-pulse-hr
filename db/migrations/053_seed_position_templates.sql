-- 053_seed_position_templates.sql
-- Seed 8 ready-to-use position templates so users have a starting point.
-- Idempotent: only inserts if templates table is empty.

INSERT INTO position_templates (
    name, title, department, employment_type, jd_text,
    required_skills, nice_to_have_skills, min_experience_years,
    weight_skills, weight_experience, weight_education, weight_certifications, weight_industry
)
SELECT * FROM (VALUES
    (
        'Senior Backend Engineer',
        'Senior Backend Engineer',
        'Engineering',
        'full-time',
        '## Senior Backend Engineer

**Location:** Hybrid · **Reports to:** Engineering Manager

### About the role
Build scalable Python services powering our platform. Own end-to-end design from API to database.

### Responsibilities
- Design and ship Python/FastAPI microservices serving 10k+ daily users
- Own PostgreSQL schema design, migrations, query optimization
- Build async pipelines using asyncio + Redis queues
- Mentor 2-3 mid-level engineers
- On-call rotation (1 week/month)

### Requirements
- 5+ years Python production experience
- Strong async/await patterns, asyncio expertise
- PostgreSQL deep knowledge (indexing, query plans, partitioning)
- Docker, Kubernetes, CI/CD pipelines
- Bachelor in CS or equivalent',
        ARRAY['python','fastapi','postgresql','asyncio','docker','kubernetes'],
        ARRAY['pgvector','rag','redis','aws','grpc'],
        5,
        0.40, 0.25, 0.10, 0.10, 0.15
    ),
    (
        'Frontend Engineer',
        'Frontend Engineer',
        'Engineering',
        'full-time',
        '## Frontend Engineer

**Stack:** TypeScript, React or Svelte, Tailwind

### Responsibilities
- Build user-facing features in modern framework
- Implement design system components
- Optimize bundle size and Core Web Vitals
- Write Playwright e2e tests

### Requirements
- 3+ years modern frontend (React, Vue, or Svelte)
- TypeScript proficiency
- CSS layout mastery (Flexbox, Grid)
- Familiar with build tools (Vite, esbuild)',
        ARRAY['typescript','react','svelte','tailwind','vite'],
        ARRAY['playwright','figma','accessibility','graphql'],
        3,
        0.40, 0.25, 0.10, 0.05, 0.20
    ),
    (
        'Senior Data Scientist (NLP)',
        'Senior Data Scientist - NLP',
        'Data',
        'full-time',
        '## Senior Data Scientist (NLP)

### Mission
Improve AI-powered matching engine and build new NLP features.

### Responsibilities
- Train + fine-tune embedding models
- Evaluate LLMs (Claude, Gemini, GPT) for extraction/classification tasks
- Build retrieval pipelines (dense + sparse + reranking)
- Ship A/B tests measuring quality lift

### Requirements
- MS or PhD in CS, ML, Statistics, or related
- 4+ years applied NLP in production
- Strong Python (PyTorch or JAX)
- Embedding models, vector search, RAG
- SQL + data wrangling',
        ARRAY['python','pytorch','embeddings','rag','sql','nlp'],
        ARRAY['pgvector','qdrant','dspy','multilingual'],
        4,
        0.45, 0.20, 0.15, 0.05, 0.15
    ),
    (
        'DevOps / Platform Engineer',
        'DevOps / Platform Engineer',
        'Engineering',
        'full-time',
        '## Senior DevOps Engineer

**Stack:** Kubernetes, Terraform, AWS, GitHub Actions

### Responsibilities
- Own production Kubernetes cluster (EKS) hosting all backend services
- Build/maintain Terraform modules for AWS infra
- CI/CD pipelines via GitHub Actions
- Observability: Prometheus, Grafana, Loki, OpenTelemetry
- Security: SOC2 controls, secret rotation, vuln scanning

### Requirements
- 5+ years DevOps/SRE in production
- Strong Kubernetes (cluster ops, Helm, operators)
- Terraform 1.5+ at scale
- Linux internals + bash + Python scripting',
        ARRAY['kubernetes','terraform','aws','github actions','prometheus','grafana'],
        ARRAY['istio','argocd','soc2','helm'],
        5,
        0.40, 0.30, 0.05, 0.15, 0.10
    ),
    (
        'HSE Manager',
        'Senior HSE Manager',
        'Corporate Affairs',
        'full-time',
        '## Senior HSE Manager

### Responsibilities
- Develop + maintain HSE policy and SOPs
- Conduct workplace inspections + risk assessments
- Lead incident investigations + root-cause analysis
- Train operations staff on safety procedures
- Liaise with regulators (OSHA, local authorities)

### Requirements
- 8+ years HSE in manufacturing/oil-gas/construction
- ISO 45001, OHSAS 18001 certified
- Bachelor degree in Engineering, Environmental Science, or HSE
- Fire Safety Management certificate
- Strong incident investigation skills (Tripod-Beta, Kelvin TOP-SET)',
        ARRAY['hse','iso 45001','ohsas 18001','risk assessment','incident investigation','osha'],
        ARRAY['tripod-beta','iso 14001','first aid','permit to work'],
        8,
        0.40, 0.25, 0.10, 0.20, 0.05
    ),
    (
        'Talent Acquisition Lead',
        'Talent Acquisition Lead',
        'People',
        'full-time',
        '## Talent Acquisition Lead

### Mission
Build and lead the in-house recruiting function.

### Responsibilities
- Own full-funnel recruiting for tech, product, ops roles
- Build recruiter team (hire 2 IC recruiters in year 1)
- Define hiring rubrics and interview loops
- Vendor management (LinkedIn, JobsDB, local agencies)

### Requirements
- 6+ years recruiting, including 2+ leading recruiters
- Tech recruiting experience
- Strong stakeholder management
- Data-driven (funnel metrics, time-to-hire, source-of-hire)',
        ARRAY['recruiting','tech hiring','ats','stakeholder management','sourcing'],
        ARRAY['greenhouse','lever','employer branding','dei'],
        6,
        0.30, 0.30, 0.10, 0.10, 0.20
    ),
    (
        'Product Manager',
        'Senior Product Manager',
        'Product',
        'full-time',
        '## Senior Product Manager

### Responsibilities
- Own product roadmap and discovery for a product area
- Write specs + work directly with eng/design/data
- Run user research + usability tests
- Define + monitor success metrics
- Stakeholder communication (exec, sales, support)

### Requirements
- 5+ years product management at SaaS / enterprise
- Strong analytical + writing skills
- Track record shipping AI/ML features a plus
- Bachelor degree or equivalent experience',
        ARRAY['product management','user research','data analysis','spec writing','roadmapping'],
        ARRAY['ai/ml','sql','figma','sql','jira'],
        5,
        0.30, 0.30, 0.10, 0.05, 0.25
    ),
    (
        'UX Designer',
        'Senior Product Designer',
        'Design',
        'full-time',
        '## Senior Product Designer

### Responsibilities
- Lead design for a major product area
- End-to-end: user research → wireframes → high-fidelity prototypes → spec
- Build + maintain design system components
- Collaborate with PM + engineering daily

### Requirements
- 5+ years SaaS / consumer product design
- Strong portfolio (interaction + visual)
- Figma + Figma variables/auto-layout mastery
- Comfortable in cross-functional ambiguity',
        ARRAY['figma','interaction design','user research','design systems','prototyping'],
        ARRAY['accessibility','animation','ux writing','swift','flutter'],
        5,
        0.40, 0.25, 0.10, 0.05, 0.20
    )
) AS t(name, title, department, employment_type, jd_text,
       required_skills, nice_to_have_skills, min_experience_years,
       weight_skills, weight_experience, weight_education, weight_certifications, weight_industry)
WHERE NOT EXISTS (SELECT 1 FROM position_templates LIMIT 1);
