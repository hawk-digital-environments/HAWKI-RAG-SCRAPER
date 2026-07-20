<script lang="ts">
	import type { Entrypoint, HostEntrypoint, SitemapEntrypoint } from '$lib/api/types';
	import Button from '$lib/ui/Button.svelte';
	import TextInput from '$lib/ui/TextInput.svelte';
	import SelectInput from '$lib/ui/SelectInput.svelte';
	import FormGroup from '$lib/ui/FormGroup.svelte';

	interface Props {
		entrypoints: Entrypoint[];
		onchange: (entries: Entrypoint[]) => void;
	}

	let { entrypoints, onchange }: Props = $props();

	let showAddMenu = $state(false);
	let expandedSitemaps = $state<Record<number, boolean>>({});

	function update(index: number, updated: Entrypoint) {
		const next = [...entrypoints];
		next[index] = updated;
		onchange(next);
	}

	function remove(index: number) {
		const next = { ...expandedSitemaps };
		delete next[index];
		expandedSitemaps = next;
		onchange(entrypoints.filter((_, i) => i !== index));
	}

	function moveUp(index: number) {
		if (index === 0) return;
		const next = [...entrypoints];
		[next[index - 1], next[index]] = [next[index], next[index - 1]];
		onchange(next);
	}

	function moveDown(index: number) {
		if (index === entrypoints.length - 1) return;
		const next = [...entrypoints];
		[next[index], next[index + 1]] = [next[index + 1], next[index]];
		onchange(next);
	}

	function addHost() {
		showAddMenu = false;
		onchange([...entrypoints, { type: 'host', src: '', protocol: 'https' }]);
	}

	function addSitemap() {
		showAddMenu = false;
		onchange([...entrypoints, { type: 'sitemap', src: '' }]);
	}

	function toggleSitemapAdvanced(index: number) {
		expandedSitemaps = { ...expandedSitemaps, [index]: !expandedSitemaps[index] };
	}

	function updateHostField(index: number, field: keyof HostEntrypoint, value: string) {
		const entry = entrypoints[index] as HostEntrypoint;
		update(index, { ...entry, [field]: value });
	}

	function updateSitemapField(index: number, field: keyof SitemapEntrypoint, value: unknown) {
		const entry = entrypoints[index] as SitemapEntrypoint;
		update(index, { ...entry, [field]: value });
	}

	function updateConflictResolution(
		index: number,
		field: 'last_modified' | 'language',
		value: string
	) {
		const entry = entrypoints[index] as SitemapEntrypoint;
		const existing = entry.conflict_resolution ?? { last_modified: 'sitemap', language: 'page' };
		update(index, {
			...entry,
			conflict_resolution: { ...existing, [field]: value }
		});
	}
</script>

<div class="entrypoint-list">
	{#each entrypoints as entry, i}
		<div class="entry-block">
			<div class="entry-header">
				<span class="entry-type-badge type-{entry.type}">{entry.type}</span>
				<div class="entry-actions">
					<Button variant="ghost" size="icon" type="button" title="Move up" disabled={i === 0} onclick={() => moveUp(i)}>↑</Button>
					<Button variant="ghost" size="icon" type="button" title="Move down" disabled={i === entrypoints.length - 1} onclick={() => moveDown(i)}>↓</Button>
					<Button variant="ghost" size="icon" type="button" title="Remove" onclick={() => remove(i)}>✕</Button>
				</div>
			</div>

			{#if entry.type === 'host'}
				<div class="entry-fields">
					<div class="field-row">
						<FormGroup label="Hostname" for="host-src-{i}" class="flex-1">
							<TextInput
								id="host-src-{i}"
								value={entry.src}
								placeholder="e.g. hawk.de"
								oninput={(e) => updateHostField(i, 'src', (e.target as HTMLInputElement).value)}
							/>
						</FormGroup>
						<FormGroup label="Protocol" for="host-proto-{i}" class="protocol-field">
							<SelectInput
								id="host-proto-{i}"
								value={entry.protocol ?? 'https'}
								onchange={(e) => updateHostField(i, 'protocol', (e.target as HTMLSelectElement).value)}
							>
								<option value="https">https</option>
								<option value="http">http</option>
							</SelectInput>
						</FormGroup>
					</div>
					<p class="hint">
						www. inference: <code>hawk.de</code> automatically includes <code>www.hawk.de</code> (root
						domain only).
					</p>
				</div>
			{:else if entry.type === 'sitemap'}
				<div class="entry-fields">
					<FormGroup label="Sitemap URL" for="sitemap-src-{i}">
						<TextInput
							id="sitemap-src-{i}"
							type="url"
							value={entry.src}
							placeholder="https://example.edu/sitemap.xml"
							oninput={(e) => updateSitemapField(i, 'src', (e.target as HTMLInputElement).value)}
						/>
					</FormGroup>

					<button class="advanced-toggle" type="button" onclick={() => toggleSitemapAdvanced(i)}>
						{expandedSitemaps[i] ? '▾' : '▸'} Advanced (conflict resolution)
					</button>

					{#if expandedSitemaps[i]}
						<div class="advanced-fields">
							<div class="field-row">
								<FormGroup label="last_modified winner" for="cr-lm-{i}" class="flex-1">
									<SelectInput
										id="cr-lm-{i}"
										value={entry.conflict_resolution?.last_modified ?? 'sitemap'}
										onchange={(e) => updateConflictResolution(i, 'last_modified', (e.target as HTMLSelectElement).value)}
									>
										<option value="sitemap">sitemap</option>
										<option value="page">page</option>
									</SelectInput>
									<p class="hint">Sitemap wins by default (more reliable).</p>
								</FormGroup>
								<FormGroup label="language winner" for="cr-lang-{i}" class="flex-1">
									<SelectInput
										id="cr-lang-{i}"
										value={entry.conflict_resolution?.language ?? 'page'}
										onchange={(e) => updateConflictResolution(i, 'language', (e.target as HTMLSelectElement).value)}
									>
										<option value="page">page</option>
										<option value="sitemap">sitemap</option>
									</SelectInput>
									<p class="hint">Page wins by default (html lang is more reliable).</p>
								</FormGroup>
							</div>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/each}

	{#if entrypoints.length === 0}
		<p class="empty-hint">No entrypoints yet. Add a host or sitemap to get started.</p>
	{/if}

	<div class="add-menu-wrap">
		{#if showAddMenu}
			<div class="add-menu">
				<button class="add-menu-item" type="button" onclick={addHost}>
					<strong>Host</strong>
					<span>A hostname the crawler starts from</span>
				</button>
				<button class="add-menu-item" type="button" onclick={addSitemap}>
					<strong>Sitemap</strong>
					<span>A sitemap.xml to seed the crawl</span>
				</button>
			</div>
		{/if}
		<Button variant="secondary" size="sm" type="button" onclick={() => (showAddMenu = !showAddMenu)}>
			+ Add entrypoint
		</Button>
	</div>
</div>

<style>
	.entrypoint-list {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.entry-block {
		border: 1px solid var(--c-border);
		border-radius: var(--radius);
		background: var(--c-surface);
	}

	.entry-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 10px;
		border-bottom: 1px solid var(--c-border-subtle);
		background: var(--c-border-subtle);
		border-radius: var(--radius) var(--radius) 0 0;
	}

	.entry-type-badge {
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		padding: 2px 7px;
		border-radius: 100px;
	}

	.type-host { background: #dbeafe; color: #1d4ed8; }
	.type-sitemap { background: #d1fae5; color: #065f46; }

	.entry-actions { display: flex; gap: 2px; }

	.entry-fields {
		padding: 12px;
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.field-row {
		display: flex;
		gap: 10px;
		align-items: flex-start;
	}

	/* FormGroup width classes passed via class prop */
	.entry-fields :global(.flex-1) { flex: 1; }
	.entry-fields :global(.protocol-field) { width: 110px; flex-shrink: 0; }

	.advanced-toggle {
		background: none;
		border: none;
		padding: 0;
		font-size: 12px;
		color: var(--c-text-secondary);
		cursor: pointer;
		text-align: left;
		margin-bottom: 10px;
	}

	.advanced-toggle:hover { color: var(--c-primary); }

	.advanced-fields {
		background: var(--c-border-subtle);
		border-radius: var(--radius-sm);
		padding: 10px;
		margin-bottom: 4px;
	}

	.hint {
		font-size: 12px;
		color: var(--c-text-muted);
		margin-top: 4px;
		line-height: 1.5;
	}

	.empty-hint {
		font-size: 13px;
		color: var(--c-text-muted);
		padding: 8px 0;
	}

	.add-menu-wrap {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 6px;
	}

	.add-menu {
		position: absolute;
		bottom: calc(100% + 4px);
		left: 0;
		background: var(--c-surface);
		border: 1px solid var(--c-border);
		border-radius: var(--radius);
		box-shadow: var(--shadow-md);
		min-width: 220px;
		overflow: hidden;
		z-index: 10;
	}

	.add-menu-item {
		display: flex;
		flex-direction: column;
		gap: 1px;
		width: 100%;
		padding: 10px 14px;
		text-align: left;
		background: none;
		border: none;
		cursor: pointer;
		border-bottom: 1px solid var(--c-border-subtle);
		font-family: var(--font-sans);
	}

	.add-menu-item:last-child { border-bottom: none; }
	.add-menu-item:hover { background: var(--c-border-subtle); }
	.add-menu-item strong { font-size: 13px; color: var(--c-text); }
	.add-menu-item span { font-size: 11px; color: var(--c-text-muted); }

	code {
		font-family: var(--font-mono);
		font-size: 11px;
		background: var(--c-border-subtle);
		padding: 1px 4px;
		border-radius: 3px;
	}
</style>
