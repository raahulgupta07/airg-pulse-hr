<script>
	import { onMount } from 'svelte';
	let { options = {}, height = '300px' } = $props();
	let container;
	let chartInstance;

	onMount(async () => {
		const echarts = await import('echarts');
		chartInstance = echarts.init(container);
		chartInstance.setOption(options);
		const resize = () => chartInstance.resize();
		window.addEventListener('resize', resize);
		return () => {
			window.removeEventListener('resize', resize);
			chartInstance.dispose();
		};
	});

	$effect(() => {
		if (chartInstance && options) {
			chartInstance.setOption(options, true);
		}
	});
</script>

<div bind:this={container} style="width: 100%; height: {height};"></div>
