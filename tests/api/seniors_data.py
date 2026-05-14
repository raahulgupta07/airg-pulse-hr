"""Senior fixture data — 8 CVs + 5 JDs + 3 positions."""

SENIORS = [
    {
        "name": "Anika Raman",
        "email": "anika.raman@example.com",
        "phone": "+1-415-555-0142",
        "location": "San Francisco, CA",
        "title": "Staff Software Engineer",
        "company": "Stripe",
        "years": 12,
        "summary": "Staff engineer specializing in distributed payments infrastructure and high-throughput services.",
        "skills": ["Go", "Kubernetes", "PostgreSQL", "gRPC", "Kafka", "AWS", "Terraform", "Python"],
        "experience": [
            ("Staff Software Engineer", "Stripe", "2021 - Present", "Lead payments routing platform handling $200B/yr volume. Built sharded ledger service in Go on Kubernetes."),
            ("Senior Software Engineer", "Datadog", "2017 - 2021", "Owned ingestion pipeline (Kafka, Go) processing 10M events/sec."),
            ("Software Engineer", "Amazon Web Services", "2013 - 2017", "Worked on EC2 control plane (Java, Python)."),
        ],
        "education": [("BS Computer Science", "MIT", "2009-2013")],
        "certs": ["AWS Solutions Architect Professional"],
    },
    {
        "name": "Diego Hernandez",
        "email": "diego.hernandez@example.com",
        "phone": "+1-512-555-0188",
        "location": "Austin, TX",
        "title": "Engineering Manager",
        "company": "Snowflake",
        "years": 14,
        "summary": "Engineering manager building data-warehouse query optimization teams across 3 timezones.",
        "skills": ["Java", "Scala", "Spark", "Snowflake", "Airflow", "Kafka", "AWS", "Leadership"],
        "experience": [
            ("Engineering Manager", "Snowflake", "2020 - Present", "Manage 3 teams (24 engineers) on query compiler. Shipped adaptive optimizer cutting p95 latency 40%."),
            ("Tech Lead", "Cloudera", "2015 - 2020", "Led Spark SQL team (8 engineers). Contributed to Apache Spark Catalyst."),
            ("Senior Engineer", "Oracle", "2011 - 2015", "Worked on Exadata storage server (C++, Java)."),
        ],
        "education": [("MS Computer Science", "Carnegie Mellon", "2009-2011"), ("BS Computer Engineering", "UT Austin", "2005-2009")],
        "certs": ["AWS Solutions Architect Associate"],
    },
    {
        "name": "Priya Sharma",
        "email": "priya.sharma@example.com",
        "phone": "+1-206-555-0177",
        "location": "Seattle, WA",
        "title": "VP of Engineering",
        "company": "Confluent",
        "years": 18,
        "summary": "VP Engineering leading 80-person org across streaming platform and developer tools.",
        "skills": ["Leadership", "Kafka", "Java", "Go", "Kubernetes", "GCP", "AWS", "Strategy"],
        "experience": [
            ("VP Engineering", "Confluent", "2022 - Present", "Lead 80 engineers across Kafka cloud and connectors. Drove ARR from $400M to $750M."),
            ("Senior Director Engineering", "LinkedIn", "2017 - 2022", "Owned messaging infra (Kafka, Espresso). Managed 6 teams."),
            ("Engineering Manager", "Microsoft", "2013 - 2017", "Built Azure Service Bus team."),
            ("Senior Engineer", "Yahoo", "2007 - 2013", "Hadoop core committer."),
        ],
        "education": [("MS Distributed Systems", "Stanford", "2005-2007"), ("BTech CSE", "IIT Bombay", "2001-2005")],
        "certs": [],
    },
    {
        "name": "Marcus Johnson",
        "email": "marcus.johnson@example.com",
        "phone": "+1-617-555-0103",
        "location": "Boston, MA",
        "title": "Senior Data Scientist",
        "company": "Wayfair",
        "years": 11,
        "summary": "Senior data scientist building large-scale ML systems for e-commerce ranking and pricing.",
        "skills": ["Python", "PyTorch", "TensorFlow", "SQL", "Spark", "AWS SageMaker", "MLflow", "Statistics"],
        "experience": [
            ("Senior Data Scientist", "Wayfair", "2020 - Present", "Built deep-learning ranker for 30M-product catalog. +$80M annual GMV."),
            ("Data Scientist II", "HubSpot", "2016 - 2020", "Owned churn prediction and lead-scoring models."),
            ("Data Analyst", "Liberty Mutual", "2014 - 2016", "Pricing analytics for auto insurance."),
        ],
        "education": [("PhD Statistics", "Harvard", "2010-2014"), ("BA Mathematics", "Williams College", "2006-2010")],
        "certs": ["AWS Machine Learning Specialty"],
    },
    {
        "name": "Yuki Tanaka",
        "email": "yuki.tanaka@example.com",
        "phone": "+1-650-555-0119",
        "location": "Mountain View, CA",
        "title": "Principal Product Manager",
        "company": "Google",
        "years": 13,
        "summary": "Principal PM leading developer-platform products with 1M+ monthly active developers.",
        "skills": ["Product Strategy", "Roadmapping", "SQL", "Python", "A/B Testing", "Figma", "Stakeholder Management"],
        "experience": [
            ("Principal Product Manager", "Google", "2019 - Present", "Lead Cloud Run product. Grew DAU 6x. Owned $300M ARR P&L."),
            ("Senior Product Manager", "Stripe", "2015 - 2019", "Launched Stripe Connect. 10x growth in marketplace partners."),
            ("Product Manager", "Square", "2012 - 2015", "Owned Square Capital lending product."),
        ],
        "education": [("MBA", "Wharton", "2010-2012"), ("BS Industrial Engineering", "Berkeley", "2006-2010")],
        "certs": [],
    },
    {
        "name": "Sofia Rossi",
        "email": "sofia.rossi@example.com",
        "phone": "+1-718-555-0166",
        "location": "Brooklyn, NY",
        "title": "Head of Design",
        "company": "Notion",
        "years": 12,
        "summary": "Head of Design building unified design system and growing team from 4 to 28 designers.",
        "skills": ["Design Leadership", "Figma", "Design Systems", "User Research", "Prototyping", "Brand"],
        "experience": [
            ("Head of Design", "Notion", "2021 - Present", "Lead 28-person design org. Shipped Notion AI UX. Grew NPS from 42 to 68."),
            ("Design Director", "Airbnb", "2017 - 2021", "Led host-platform design. Owned design system DLS."),
            ("Senior Designer", "IDEO", "2013 - 2017", "Client work for Apple, Ford, Pepsi."),
        ],
        "education": [("BFA Graphic Design", "RISD", "2009-2013")],
        "certs": [],
    },
    {
        "name": "Ahmed Al-Mansour",
        "email": "ahmed.almansour@example.com",
        "phone": "+1-650-555-0124",
        "location": "Palo Alto, CA",
        "title": "Chief Technology Officer",
        "company": "Vellum AI",
        "years": 20,
        "summary": "CTO and co-founder building AI orchestration platform. Scaled from 0 to $40M ARR.",
        "skills": ["Leadership", "Python", "Go", "Kubernetes", "GCP", "LLMs", "Architecture", "Fundraising"],
        "experience": [
            ("CTO & Co-Founder", "Vellum AI", "2022 - Present", "Built engineering org from 2 to 45. Raised $50M Series B."),
            ("VP Engineering", "Looker (Google Cloud)", "2017 - 2022", "Led platform team through $2.6B Google acquisition."),
            ("Engineering Director", "Salesforce", "2011 - 2017", "Owned Heroku PostgreSQL service."),
            ("Senior Engineer", "Twitter", "2007 - 2011", "Worked on Tweet timeline architecture."),
        ],
        "education": [("MS Computer Science", "Stanford", "2005-2007"), ("BS Computer Science", "Caltech", "2001-2005")],
        "certs": ["Google Cloud Professional Cloud Architect"],
    },
    {
        "name": "Elena Volkov",
        "email": "elena.volkov@example.com",
        "phone": "+1-303-555-0192",
        "location": "Denver, CO",
        "title": "Director of Platform Engineering",
        "company": "Discord",
        "years": 15,
        "summary": "Director of Platform leading SRE, observability, and infra-platform teams (32 engineers).",
        "skills": ["SRE", "Kubernetes", "Terraform", "Go", "Rust", "Observability", "Incident Response", "AWS"],
        "experience": [
            ("Director Platform Engineering", "Discord", "2020 - Present", "Lead 32 engineers. Drove p99 latency from 800ms to 120ms. SLA 99.99%."),
            ("Senior Engineering Manager", "Cloudflare", "2016 - 2020", "Led edge-platform team (12 engineers)."),
            ("Staff SRE", "Uber", "2012 - 2016", "On-call leader. Built incident-response automation."),
            ("DevOps Engineer", "Etsy", "2009 - 2012", "Continuous-deployment pioneer."),
        ],
        "education": [("BS Computer Science", "University of Colorado Boulder", "2005-2009")],
        "certs": ["Certified Kubernetes Administrator", "AWS DevOps Engineer Professional"],
    },
]


JDS = [
    {
        "title": "Head of AI Platform",
        "department": "Engineering",
        "seniority_level": "Director",
        "employment_type": "full-time",
        "location": "San Francisco, CA",
        "work_mode": "hybrid",
        "jd_text": (
            "We are seeking a Head of AI Platform to lead our LLM infrastructure organization. "
            "You will own the full ML platform stack including model serving, inference optimization, "
            "fine-tuning pipelines, and evaluation frameworks. Manage a team of 20+ engineers across "
            "ML infra, MLOps, and applied research. Required: 12+ years engineering experience, "
            "5+ years management, deep expertise in PyTorch, Kubernetes, distributed training, "
            "and at least one production LLM deployment. Bonus: experience with vLLM, Ray, or "
            "transformer-architecture optimization. Strong technical writing and stakeholder management. "
            "Education: MS or PhD in CS, ML, or related field preferred. "
            "Tech stack: Python, PyTorch, Kubernetes, GCP, Ray, vLLM, Triton."
        ),
    },
    {
        "title": "VP of Engineering",
        "department": "Engineering",
        "seniority_level": "VP",
        "employment_type": "full-time",
        "location": "Remote (US)",
        "work_mode": "remote",
        "jd_text": (
            "VP of Engineering to lead a 60-person engineering organization across product, "
            "platform, and infrastructure. You will report to the CTO and own delivery, hiring, "
            "and engineering culture. Must have managed 50+ engineers previously, scaled an org "
            "through Series B to D, and led at least one major architectural transformation. "
            "Strong opinions on remote-first practices, async communication, and engineering "
            "excellence. Required: 15+ years experience, 7+ years senior leadership, track record "
            "of hiring senior talent, experience with SaaS or developer tools. "
            "Tech background: Go, Java, Kubernetes, AWS or GCP, distributed systems."
        ),
    },
    {
        "title": "Staff Backend Engineer",
        "department": "Engineering",
        "seniority_level": "Staff",
        "employment_type": "full-time",
        "location": "New York, NY",
        "work_mode": "hybrid",
        "jd_text": (
            "Staff Backend Engineer for our payments platform team. You will architect and lead "
            "implementation of high-throughput, low-latency services processing $1B+/year in "
            "transaction volume. Required: 10+ years backend engineering, deep expertise in Go "
            "or Java, PostgreSQL at scale, distributed systems patterns (sharding, consensus, "
            "CDC), and Kubernetes. Experience with payments, ledger systems, or financial "
            "infrastructure strongly preferred. Strong written and verbal communication, mentor "
            "to senior engineers. Tech stack: Go, PostgreSQL, Kafka, Kubernetes, AWS, Terraform, gRPC."
        ),
    },
    {
        "title": "Director of Data Science",
        "department": "Data",
        "seniority_level": "Director",
        "employment_type": "full-time",
        "location": "Boston, MA",
        "work_mode": "hybrid",
        "jd_text": (
            "Director of Data Science to lead our 18-person DS organization across personalization, "
            "pricing, and forecasting. You will own ML strategy, model governance, and platform "
            "investment decisions. Must have shipped production ML systems serving 10M+ users, "
            "built and led DS teams of 10+, and partnered closely with product and engineering "
            "leadership. Required: PhD or MS in quantitative field, 10+ years applied ML, 5+ "
            "years management, expertise in PyTorch or TensorFlow, SQL, Python, and statistical "
            "rigor. Tech: Python, PyTorch, Spark, MLflow, AWS SageMaker, Snowflake."
        ),
    },
    {
        "title": "Principal Site Reliability Engineer",
        "department": "Infrastructure",
        "seniority_level": "Principal",
        "employment_type": "full-time",
        "location": "Seattle, WA",
        "work_mode": "remote",
        "jd_text": (
            "Principal SRE to drive reliability strategy for our consumer platform serving 200M+ "
            "users. You will set technical direction for observability, incident response, capacity "
            "planning, and chaos engineering. Required: 12+ years SRE/infrastructure, deep "
            "Kubernetes expertise, Go or Rust proficiency, experience designing 4-nines or better "
            "systems, and proven track record reducing MTTR. You will partner with VP-level "
            "stakeholders and mentor staff and senior engineers. Tech stack: Kubernetes, Go, Rust, "
            "Terraform, AWS, Prometheus, OpenTelemetry, Envoy, eBPF."
        ),
    },
]


POSITIONS = [
    {
        "title": "Head of AI Platform",
        "department": "Engineering",
        "location": "San Francisco, CA",
        "employment_type": "full-time",
        "required_skills": ["Python", "PyTorch", "Kubernetes", "GCP", "LLMs", "Leadership"],
        "nice_to_have_skills": ["Ray", "vLLM", "Triton"],
        "min_experience_years": 12,
        "education_level": "MS",
        "industry_keywords": ["ai", "ml", "infrastructure"],
    },
    {
        "title": "Staff Backend Engineer (Payments)",
        "department": "Engineering",
        "location": "New York, NY",
        "employment_type": "full-time",
        "required_skills": ["Go", "PostgreSQL", "Kubernetes", "Kafka", "AWS"],
        "nice_to_have_skills": ["Terraform", "gRPC"],
        "min_experience_years": 10,
        "education_level": "BS",
        "industry_keywords": ["payments", "fintech"],
    },
    {
        "title": "Director of Data Science",
        "department": "Data",
        "location": "Boston, MA",
        "employment_type": "full-time",
        "required_skills": ["Python", "PyTorch", "Spark", "SQL", "Leadership"],
        "nice_to_have_skills": ["MLflow", "AWS SageMaker"],
        "min_experience_years": 10,
        "education_level": "MS",
        "industry_keywords": ["data", "ml", "ecommerce"],
    },
]
