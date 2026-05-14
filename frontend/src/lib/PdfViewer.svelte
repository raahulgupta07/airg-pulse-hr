<script>
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';

	let {
		candidateId = '',
		show = false,
		onClose = () => {},
	} = $props();

	// --- State ---
	let screenshots = $state([]);
	let currentPage = $state(0);
	let loading = $state(true);
	let reprocessing = $state(false);
	let noScreenshots = $state(false);

	$effect(() => {
		const s = show;
		const cid = candidateId;
		if (s && cid) {
			untrack(() => loadScreenshots());
		}
	});

	async function loadScreenshots() {
		loading = true;
		noScreenshots = false;
		try {
			const candidate = await apiJson(`/candidates/${candidateId}`);
			const shots = candidate.screenshots || candidate.pdf_screenshots || [];
			if (shots.length > 0) {
				screenshots = shots;
				currentPage = 0;
			} else if (candidate.pdf_path) {
				// Try to construct screenshot paths from pdf_path
				const pageCount = candidate.page_count || 0;
				if (pageCount > 0) {
					const basePath = candidate.pdf_path.replace(/\.pdf$/i, '');
					screenshots = Array.from({ length: pageCount }, (_, i) => `/api/candidates/${candidateId}/screenshot/${i + 1}`);
					currentPage = 0;
				} else {
					noScreenshots = true;
				}
			} else {
				noScreenshots = true;
			}
		} catch (e) {
			console.error('Failed to load screenshots:', e);
			noScreenshots = true;
		}
		loading = false;
	}

	async function reprocess() {
		reprocessing = true;
		try {
			await apiJson(`/candidates/${candidateId}/reprocess`, { method: 'POST' });
			await loadScreenshots();
		} catch (e) {
			console.error('Reprocess failed:', e);
		}
		reprocessing = false;
	}

	function prevPage() {
		if (currentPage > 0) currentPage--;
	}

	function nextPage() {
		if (currentPage < screenshots.length - 1) currentPage++;
	}

	function handleClose() {
		screenshots = [];
		currentPage = 0;
		onClose();
	}
</script>

{#if show}
<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="viewer-overlay"
	onclick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
>
	<div class="viewer-panel ink-border animate-slide-in">
		<!-- Header -->
		<div class="dark-title-bar flex items-center justify-between" style="font-size: 11px; flex-shrink: 0;">
			<span class="flex items-center gap-2">
				<span class="material-symbols-outlined" style="font-size: 16px;">picture_as_pdf</span>
				CV Viewer
				{#if screenshots.length > 0}
					<span style="font-weight: 400; font-size: 10px;">
						Page {currentPage + 1} of {screenshots.length}
					</span>
				{/if}
			</span>
			<button onclick={handleClose} style="background: none; border: none; color: var(--color-surface); cursor: pointer; padding: 2px;">
				<span class="material-symbols-outlined" style="font-size: 18px;">close</span>
			</button>
		</div>

		{#if loading}
			<div class="flex items-center justify-center" style="flex: 1;">
				<div class="typing-indicator"><span></span><span></span><span></span></div>
			</div>
		{:else if noScreenshots}
			<div class="flex flex-col items-center justify-center gap-4" style="flex: 1; padding: 40px;">
				<span class="material-symbols-outlined" style="font-size: 64px; color: var(--color-on-surface-dim);">description</span>
				<p style="font-size: 14px; font-weight: 900; text-transform: uppercase;">CV not processed yet</p>
				<p style="font-size: 12px; color: var(--color-on-surface-dim);">Screenshots are generated during CV processing.</p>
				<button class="send-btn" onclick={reprocess} disabled={reprocessing} style="font-size: 11px;">
					{#if reprocessing}
						<span class="typing-indicator" style="display: inline-flex; gap: 2px; vertical-align: middle; margin-right: 4px;"><span></span><span></span><span></span></span>
						Reprocessing...
					{:else}
						<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">refresh</span>
						Reprocess CV
					{/if}
				</button>
			</div>
		{:else}
			<div class="viewer-body">
				<!-- Sidebar Thumbnails -->
				<div class="thumb-sidebar">
					{#each screenshots as shot, i}
						<button
							class="thumb-item"
							class:thumb-active={currentPage === i}
							onclick={() => currentPage = i}
						>
							<img src={shot} alt="Page {i + 1}" style="width: 100%; height: auto; display: block;" />
							<span class="thumb-number">{i + 1}</span>
						</button>
					{/each}
				</div>

				<!-- Main Page View -->
				<div class="main-view">
					<div class="page-container">
						<img
							src={screenshots[currentPage]}
							alt="Page {currentPage + 1}"
							style="width: 100%; height: auto; display: block; border: 2px solid var(--color-on-surface);"
						/>
					</div>

					<!-- Page Nav -->
					<div class="page-nav flex items-center justify-center gap-3">
						<button
							class="btn-secondary"
							onclick={prevPage}
							disabled={currentPage === 0}
							style="font-size: 10px; padding: 6px 12px;"
						>
							<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">chevron_left</span>
							Prev
						</button>
						<span style="font-size: 12px; font-weight: 900; text-transform: uppercase;">
							{currentPage + 1} / {screenshots.length}
						</span>
						<button
							class="btn-secondary"
							onclick={nextPage}
							disabled={currentPage === screenshots.length - 1}
							style="font-size: 10px; padding: 6px 12px;"
						>
							Next
							<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">chevron_right</span>
						</button>
					</div>
				</div>
			</div>
		{/if}
	</div>
</div>
{/if}

<style>
	.viewer-overlay {
		position: fixed;
		inset: 0;
		background: rgba(56, 56, 50, 0.5);
		z-index: 1000;
		display: flex;
		justify-content: flex-end;
	}

	.viewer-panel {
		width: 45%;
		min-width: 400px;
		max-width: 700px;
		height: 100%;
		background: var(--color-surface);
		display: flex;
		flex-direction: column;
		animation: panelSlideIn 0.3s ease-out;
		overflow: hidden;
	}

	.viewer-body {
		flex: 1;
		display: flex;
		overflow: hidden;
	}

	.thumb-sidebar {
		width: 90px;
		flex-shrink: 0;
		overflow-y: auto;
		padding: 8px;
		background: var(--color-surface-container);
		border-right: 2px solid var(--color-on-surface);
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.thumb-item {
		position: relative;
		cursor: pointer;
		background: white;
		border: 2px solid var(--color-outline-variant);
		padding: 2px;
		transition: border-color 0.15s;
	}

	.thumb-item:hover {
		border-color: var(--color-on-surface);
	}

	.thumb-active {
		border-color: var(--color-primary-container) !important;
		border-width: 3px;
		box-shadow: 0 0 0 1px var(--color-primary);
	}

	.thumb-number {
		position: absolute;
		bottom: 2px;
		right: 2px;
		background: var(--color-on-surface);
		color: var(--color-surface);
		font-size: 8px;
		font-weight: 900;
		padding: 1px 4px;
	}

	.main-view {
		flex: 1;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.page-container {
		flex: 1;
		overflow-y: auto;
		padding: 16px;
		background: var(--color-surface-highest);
	}

	.page-nav {
		flex-shrink: 0;
		padding: 10px;
		background: var(--color-surface);
		border-top: 2px solid var(--color-on-surface);
	}

	@media (max-width: 768px) {
		.viewer-panel {
			width: 100%;
			min-width: unset;
		}
		.thumb-sidebar {
			width: 60px;
		}
	}
</style>
