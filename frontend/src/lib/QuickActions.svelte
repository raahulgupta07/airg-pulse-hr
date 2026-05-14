<script>
	// Brutalist quick-actions strip for candidate profile
	// Props: candidateId, candidate, onAiSummary, onEmail
	let {
		candidateId,
		candidate = null,
		onAiSummary = () => {},
		onExportReport = () => {},
		onEmail = () => {},
	} = $props();

	let showMore = $state(false);

	function stub(label) {
		alert(`${label} — Coming soon`);
	}

	function confirmReject() {
		if (confirm(`Reject candidate "${candidate?.name || '#' + candidateId}"? This action cannot be undone (stub).`)) {
			alert('Reject — Coming soon');
		}
	}

	function exportJson() {
		try {
			const blob = new Blob([JSON.stringify(candidate, null, 2)], { type: 'application/json' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `candidate_${candidateId}.json`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			alert('Export failed');
		}
		showMore = false;
	}

	function archive() {
		stub('Archive');
		showMore = false;
	}

	function copyLink() {
		try {
			navigator.clipboard.writeText(window.location.href);
			alert('Profile link copied');
		} catch { alert('Copy failed'); }
		showMore = false;
	}
</script>

<div class="qa-strip">
	<button class="qa-btn" onclick={() => stub('Attach to Position')} title="Attach to a position">
		<span class="qa-icon-text">+</span>
		<span>Attach to Position</span>
	</button>

	<button class="qa-btn" onclick={onExportReport} title="Export full candidate report (DOCX)">
		<span class="material-symbols-outlined qa-icon">description</span>
		<span>Export Report</span>
	</button>

	<button class="qa-btn" onclick={onEmail} title="Send email">
		<span class="material-symbols-outlined qa-icon">mail</span>
		<span>Email</span>
	</button>

	<button class="qa-btn" onclick={() => stub('Move Stage')} title="Move pipeline stage">
		<span class="material-symbols-outlined qa-icon">play_arrow</span>
		<span>Move Stage</span>
	</button>

	<div class="qa-more-wrap">
		<button class="qa-btn" onclick={() => showMore = !showMore} title="More actions">
			<span class="qa-icon-text qa-dots">⋮</span>
			<span>More</span>
		</button>
		{#if showMore}
			<div class="qa-more-menu">
				<button onclick={exportJson}>Export JSON</button>
				<button onclick={archive}>Archive</button>
				<button onclick={copyLink}>Copy Link</button>
			</div>
		{/if}
	</div>
</div>

<style>
	.qa-strip {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		margin-top: 14px;
	}
	.qa-btn {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 6px 12px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 10px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		background: var(--color-surface, #feffd6);
		color: var(--color-on-surface, #383832);
		border: 2px solid var(--color-on-surface, #383832);
		border-right-width: 3px;
		border-bottom-width: 3px;
		cursor: pointer;
		transition: transform 0.05s ease, background 0.1s ease;
	}
	.qa-btn:hover {
		background: var(--color-accent-soft, #f5ece8);
	}
	.qa-btn:active {
		transform: translate(1px, 1px);
		border-right-width: 2px;
		border-bottom-width: 2px;
	}
	.qa-primary {
		background: var(--color-accent, #c96342);
		color: #fff;
	}
	.qa-primary:hover {
		background: var(--color-accent, #c96342);
		opacity: 0.9;
	}
	.qa-danger:hover {
		background: #ff3b30;
		color: #fff;
	}
	.qa-icon {
		font-size: 14px;
	}
	.qa-icon-text {
		font-size: 14px;
		font-weight: 900;
		line-height: 1;
		display: inline-block;
		min-width: 10px;
		text-align: center;
	}
	.qa-dots {
		letter-spacing: 0;
		transform: scale(1.3);
	}
	.qa-more-wrap {
		position: relative;
	}
	.qa-more-menu {
		position: absolute;
		top: calc(100% + 4px);
		right: 0;
		min-width: 160px;
		background: var(--color-surface, #feffd6);
		border: 2px solid var(--color-on-surface, #383832);
		border-right-width: 3px;
		border-bottom-width: 3px;
		box-shadow: 4px 4px 0 rgba(56, 56, 50, 0.15);
		z-index: 50;
		display: flex;
		flex-direction: column;
	}
	.qa-more-menu button {
		text-align: left;
		padding: 8px 12px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 11px;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		background: var(--color-surface, #feffd6);
		border: none;
		border-bottom: 1px solid rgba(56, 56, 50, 0.15);
		color: var(--color-on-surface, #383832);
		cursor: pointer;
	}
	.qa-more-menu button:last-child {
		border-bottom: none;
	}
	.qa-more-menu button:hover {
		background: var(--color-accent-soft, #f5ece8);
	}
</style>
