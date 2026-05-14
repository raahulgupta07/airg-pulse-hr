<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	onMount(() => goto('/admin?tab=email-templates', { replaceState: true }));
</script>
