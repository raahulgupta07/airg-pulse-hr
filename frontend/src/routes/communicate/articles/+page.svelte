<script>
  import ComingSoon from '$lib/communicate/ComingSoon.svelte';

  const sample = `<strong>Happy International Women's Day, Team! 🌸</strong>
<br><br>
Today, we celebrate the strength, resilience, and brilliance of every woman across our Group — leaders, engineers, designers, finance partners, and every role in between.
<br><br>
This year's theme: <strong>"Inspire Inclusion."</strong>
<br><br>
Throughout March we're hosting:
<br>• Coffee chats with our female leadership
<br>• A panel: "Building careers across CHL, CMHL, TBO"
<br>• Recognition awards on our SharePoint wall
<br><br>
<span style="opacity: 0.5;">[Auto-generated themed image will appear here]</span>`;
</script>

<svelte:head><title>Articles · City Agent Pulse</title></svelte:head>

<ComingSoon
  feature="articles"
  title="Articles"
  tagline="Holiday + culture posts: Women's Day, Father's Day, Mother's Day, Value Awards, EAP, Thadingyut, Bonus / Increment — and any custom occasion."
  steps={[
    'Pick occasion',
    'AI writes article body',
    'AI generates image',
    'Preview + edit',
    'Email + post to SharePoint'
  ]}
  samplePreview={sample}
/>
