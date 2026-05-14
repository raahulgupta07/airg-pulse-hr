<script>
  import ComingSoon from '$lib/communicate/ComingSoon.svelte';

  const sample = `<strong>Subject:</strong> Invitation — Q4 Town Hall · 28 Oct, 4:00 PM
<br><br>
Dear Team,
<br><br>
You are cordially invited to our Q4 Town Hall on <strong>Friday, 28th October 2026 at 4:00 PM</strong> at the City Holdings Auditorium (Bahan, Yangon). Live stream available via SharePoint.
<br><br>
Agenda:
<br>• Q3 results &amp; Q4 priorities
<br>• Group movements &amp; new starters
<br>• Open Q&amp;A with the Group CEO
<br><br>
Please confirm attendance by 25th October.
<br><br>
<span style="opacity: 0.5;">[Auto-generated banner image will appear here]</span>`;
</script>

<svelte:head><title>Invitations · City Agent Pulse</title></svelte:head>

<ComingSoon
  feature="invitations"
  title="Invitations"
  tagline="Webinar / event invites: AI body + AI-generated banner image, send via email + post to SharePoint in one click."
  steps={[
    'Open invitation template',
    'AI writes invite from topic',
    'AI generates event image',
    'Add date + time + venue',
    'Email + post to SharePoint'
  ]}
  samplePreview={sample}
/>
