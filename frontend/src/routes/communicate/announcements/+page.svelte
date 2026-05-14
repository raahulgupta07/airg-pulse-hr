<script>
  import ComingSoon from '$lib/communicate/ComingSoon.svelte';

  const sample = `<strong>PRIVATE &amp; CONFIDENTIAL</strong> &nbsp;&nbsp; 30 September 2025
<br><br>
<strong>Organizational Announcement: Group Movements &amp; Leadership Updates</strong>
<br><br>
<em>Group Finance</em>
<br><br>
I am pleased to share some important leadership movements within our Finance function, effective 1st October 2025.
<br><br>
<strong>Ma Tint Tint Shun Wai</strong>, currently Head of Tax &amp; Treasury at CHL, will be transferring to The Brand Origin Co., Ltd (TBO) as Financial Controller. In her new role, she will oversee financial planning, treasury management, and regulatory compliance...
<br><br>
<span style="opacity: 0.5;">— preview truncated —</span>`;
</script>

<svelte:head><title>Announcements · City Agent Pulse</title></svelte:head>

<ComingSoon
  feature="announcements"
  title="Announcements"
  tagline="Auto-draft org movement, promotion, new starter, transfer, and leadership update letters in 30s — AI fills body from your structured fields."
  steps={[
    'Pick template (5 types)',
    'Fill name + role + effective date',
    'AI writes the letter',
    'Preview + edit inline',
    'Send via group email'
  ]}
  samplePreview={sample}
/>
