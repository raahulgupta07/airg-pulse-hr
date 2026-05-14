<script>
  import ComingSoon from '$lib/communicate/ComingSoon.svelte';

  const sample = `<strong>You:</strong> Who are the top 3 backend engineers we've interviewed in Q3?
<br><br>
<strong>Copilot:</strong>
<br><br>
Based on Q3 hiring data:
<br>1. <strong>Aisha Zaw</strong> — 71% match for Senior Backend role · 6yrs · pgvector + RAG experience · advanced to offer
<br>2. <strong>Tomas Lin</strong> — 68% match · 8yrs FastAPI + Postgres · in final interview
<br>3. <strong>Priya Sharma</strong> — 64% match · 5yrs async Python + K8s · screened, awaiting tech round
<br><br>
Want me to draft a comparison memo, or schedule a follow-up with any of them?`;
</script>

<svelte:head><title>Copilot · City Agent Pulse</title></svelte:head>

<ComingSoon
  feature="copilot"
  title="Copilot"
  tagline="Ask anything about your hiring funnel — candidates, positions, analytics, policies. Multi-step reasoning with 11 tools across CVs, JDs, pipelines, brain, and email drafting."
  steps={[
    'Type a question in plain English',
    'Copilot picks the right tool',
    'Reads from CVs / JDs / pipeline / brain',
    'Streams an answer with citations',
    'Drafts an action (email / shortlist / move stage)'
  ]}
  samplePreview={sample}
/>
