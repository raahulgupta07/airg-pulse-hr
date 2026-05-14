<script>
	import { apiJson, getToken } from '$lib/api';

	let { candidateId, fileType = '', fileName = '' } = $props();
	const ext = $derived((fileType || '').toLowerCase());
	const token = $derived(getToken() || '');
	// Fallback URLs (legacy, leak token via Referer/history). Replaced by signed URL when available.
	const legacyFileUrl = $derived(`/api/candidates/${candidateId}/file${token ? `?token=${encodeURIComponent(token)}` : ''}`);
	const legacyDownloadUrl = $derived(`/api/candidates/${candidateId}/file?download=1${token ? `&token=${encodeURIComponent(token)}` : ''}`);
	let signedFileUrl = $state('');
	let signedReady = $state(false);
	const fileUrl = $derived(signedFileUrl || legacyFileUrl);
	const downloadUrl = $derived(signedFileUrl ? `${signedFileUrl}${signedFileUrl.includes('?') ? '&' : '?'}download=1` : legacyDownloadUrl);
	let zoom = $state(100);

	// Fetch a short-lived signed URL so the bearer token never appears in iframe src
	// (which would leak via browser history + Referer headers). Falls back to legacy
	// token-in-query behaviour if the backend endpoint is not deployed (404).
	$effect(() => {
		if (!candidateId) return;
		signedReady = false;
		signedFileUrl = '';
		(async () => {
			try {
				const data = await apiJson(`/candidates/${candidateId}/file/sign`);
				if (data?.url) {
					signedFileUrl = data.url.startsWith('/api/') ? data.url : `/api${data.url}`;
				}
			} catch (e) {
				console.warn('[DocViewer] signed URL endpoint unavailable, falling back to token query', e?.message || e);
			} finally {
				signedReady = true;
			}
		})();
	});

	// Screenshots state for DOCX/fallback rendering
	let screenshots = $state([]);
	let screenshotsLoading = $state(false);
	let screenshotsError = $state('');

	// DOCX inline render state (mammoth → HTML)
	let docxHtml = $state('');
	let docxLoading = $state(false);
	let docxError = $state('');

	const isImage = $derived(['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext));
	const isPdf = $derived(ext === 'pdf');
	const isDocx = $derived(['docx', 'doc'].includes(ext));

	$effect(() => {
		if (isDocx && candidateId && fileUrl && signedReady) {
			loadDocxInline();
			loadScreenshots();
		}
	});

	async function loadDocxInline() {
		docxLoading = true;
		docxError = '';
		docxHtml = '';
		try {
			const mammoth = await import('mammoth/mammoth.browser.js');
			const res = await fetch(fileUrl);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const buf = await res.arrayBuffer();
			const result = await mammoth.convertToHtml({ arrayBuffer: buf });
			docxHtml = result.value || '';
			if (!docxHtml) docxError = 'Empty document';
		} catch (e) {
			docxError = e?.message || 'Failed to render DOCX';
		}
		docxLoading = false;
	}

	async function loadScreenshots() {
		screenshotsLoading = true;
		screenshotsError = '';
		try {
			const data = await apiJson(`/candidates/${candidateId}/artifacts`);
			const paths = data?.screenshots?.paths || [];
			screenshots = paths.map((p, i) => ({ page: i + 1, path: p }));
			if (screenshots.length === 0) {
				screenshotsError = 'No screenshots available — download original document.';
			}
		} catch (e) {
			screenshotsError = 'Screenshots not available — download original document.';
			screenshots = [];
		}
		screenshotsLoading = false;
	}

	const btnStyle = "padding: 4px 10px; border: 2px solid var(--color-surface); background: transparent; color: var(--color-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; cursor: pointer; letter-spacing: 0.05em;";
</script>

<style>
	:global(.docx-render h1) { font-size: 22px; font-weight: 900; margin: 18px 0 10px; color: var(--color-on-surface, #2c2c2c); }
	:global(.docx-render h2) { font-size: 18px; font-weight: 900; margin: 14px 0 8px; color: var(--color-accent, #c96342); }
	:global(.docx-render h3) { font-size: 15px; font-weight: 700; margin: 10px 0 6px; }
	:global(.docx-render p) { margin: 6px 0; }
	:global(.docx-render ul), :global(.docx-render ol) { margin: 6px 0 6px 22px; }
	:global(.docx-render li) { margin: 3px 0; }
	:global(.docx-render table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
	:global(.docx-render td), :global(.docx-render th) { border: 1px solid #ccc; padding: 6px 10px; vertical-align: top; }
	:global(.docx-render strong) { font-weight: 700; }
	:global(.docx-render img) { max-width: 100%; height: auto; }
</style>

<div class="ink-border stamp-shadow" style="background: var(--color-surface-bright); height: calc(100vh - 140px); max-height: calc(100vh - 140px); display: flex; flex-direction: column; overflow: hidden;">
	<div class="dark-title-bar flex items-center justify-between" style="gap: 8px; flex-wrap: wrap; position: sticky; top: 0; z-index: 5;">
		<span style="font-size: 11px;">DOC · {fileName || 'source document'} · {ext.toUpperCase() || 'UNKNOWN'}</span>
		<div style="display:flex; gap:6px; align-items:center;">
			{#if isImage}
				<button style={btnStyle} onclick={() => zoom = Math.max(50, zoom - 25)} aria-label="zoom out">− ZOOM</button>
				<span style="font-size: 11px; color: var(--color-surface); font-weight: 700; min-width: 42px; text-align: center;">{zoom}%</span>
				<button style={btnStyle} onclick={() => zoom = Math.min(200, zoom + 25)} aria-label="zoom in">+ ZOOM</button>
			{/if}
			<a href={downloadUrl} download={fileName} style={btnStyle + 'text-decoration:none; display:inline-block;'}>DOWNLOAD</a>
		</div>
	</div>
	<div style="padding: 14px; flex: 1 1 auto; min-height: 0; overflow-y: auto; overflow-x: hidden; background: #fafafa; display:flex; align-items:flex-start; justify-content:center;">
		{#if isImage}
			<img src={fileUrl} alt={fileName} style="width: {zoom}%; height: auto; object-fit: contain; border: 2px solid var(--color-on-surface);" />
		{:else if isPdf}
			<iframe
				src={fileUrl}
				title={fileName}
				style="width: 100%; height: 100%; min-height: 100%; flex: 1 1 auto; border: 2px solid var(--color-on-surface); background: white;"
				onload={(e) => { /* loaded */ }}
			></iframe>
		{:else if isDocx}
			<div style="width: 100%; max-width: 900px; margin: 0 auto;">
				{#if docxLoading}
					<div style="padding: 40px; text-align: center; font-size: 12px; font-weight: 700; text-transform: uppercase;">Rendering DOCX…</div>
				{:else if docxHtml}
					<div class="docx-render" style="background: white; padding: 32px 44px; border: 2px solid var(--color-on-surface); font-family: Georgia, 'Times New Roman', serif; font-size: 14px; line-height: 1.55; color: #1a1a1e;">
						{@html docxHtml}
					</div>
					{#if screenshots.length > 0}
						<div style="margin-top: 14px; font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; opacity: 0.6;">Screenshots (pipeline) — {screenshots.length} page(s)</div>
					{/if}
				{:else}
					<div style="padding: 40px; text-align: center; opacity: 0.7; font-size: 13px;">
						<div style="margin-bottom: 12px;">{docxError || 'No native preview for DOCX.'}</div>
						<a href={fileUrl} download={fileName} style="display: inline-block; padding: 8px 16px; border: 2px solid var(--color-on-surface); background: var(--color-primary-container); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 900; text-transform: uppercase; text-decoration: none; color: var(--color-on-surface);">DOWNLOAD ORIGINAL</a>
					</div>
				{/if}
			</div>
		{:else}
			<div style="padding: 40px; text-align: center; opacity: 0.7; font-size: 13px;">
				<div style="margin-bottom: 12px;">No native preview for {ext || 'this format'}.</div>
				<a href={fileUrl} download={fileName} style="display: inline-block; padding: 8px 16px; border: 2px solid var(--color-on-surface); background: var(--color-primary-container); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 900; text-transform: uppercase; text-decoration: none; color: var(--color-on-surface);">DOWNLOAD ORIGINAL</a>
			</div>
		{/if}
	</div>
</div>
