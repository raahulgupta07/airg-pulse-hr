<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	onMount(() => goto('/admin?tab=integrations', { replaceState: true }));
</script>
