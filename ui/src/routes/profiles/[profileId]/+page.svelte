<script lang="ts">
	import type { PageData } from './$types';
	import type { Entrypoint } from '$lib/api/types';
	import Button from '$lib/ui/Button.svelte';
	import Card from '$lib/ui/Card.svelte';
	import Alert from '$lib/ui/Alert.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import Breadcrumb from '$lib/ui/Breadcrumb.svelte';
	import TableWrap from '$lib/ui/TableWrap.svelte';
	import EmptyState from '$lib/ui/EmptyState.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import { deleteProfile } from '$lib/api';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';

	let { data }: { data: PageData } = $props();

	let confirmDelete = $state(false);
	let jsonOpen = $state(false);

	const canDelete = $derived(data.tasks.length === 0);

	const profileJson = $derived(
		JSON.stringify((({ id, ...rest }) => rest)(data.profile), null, 2)
	);

	function entrypointLabel(ep: Entrypoint): string {
		if (ep.type === 'host') return `${ep.protocol ?? 'https'}://${ep.src}`;
		return ep.src;
	}

	async function handleDelete() {
		await deleteProfile(data.profile.id);
		await goto(`${base}/profiles`);
	}
</script>

<svelte:head><title>{data.profile.name} — RAG Interface</title></svelte:head>

<PageContent title={data.profile.name}>
	{#snippet breadcrumb()}
		<Breadcrumb items={[{ label: 'Profiles', href: `${base}/profiles` }, { label: data.profile.name }]} />
	{/snippet}
	{#snippet actions()}
		<Button variant="secondary" href="{base}/tasks/new?profileId={data.profile.id}">+ Create task</Button>
		<Button variant="secondary" href="{base}/profiles/{data.profile.id}/edit">✎ Edit</Button>
		{#if canDelete}
			<Button variant="danger" onclick={() => (confirmDelete = true)}>Delete</Button>
		{:else}
			<Button variant="danger" disabled title="Used by {data.tasks.length} task(s)">Delete</Button>
		{/if}
	{/snippet}

	{#if !canDelete}
		<div class="mb-4">
			<Alert variant="warning">
				This profile is used by <strong>{data.tasks.length} task{data.tasks.length > 1 ? 's' : ''}</strong>
				({data.tasks.map((t) => t.name).join(', ')}). Delete or reassign those tasks before
				deleting this profile.
			</Alert>
		</div>
	{/if}

	<!-- Behavior -->
	<div class="mb-4">
		<Card title="Behavior">
			<div class="meta-grid">
				<div class="meta-item">
					<span class="meta-label">Max execution time</span>
					<span class="meta-value mono">{data.profile.max_execution_time}</span>
				</div>
				<div class="meta-item">
					<span class="meta-label">Max storage time</span>
					<span class="meta-value mono">{data.profile.max_storage_time}</span>
				</div>
				<div class="meta-item">
					<span class="meta-label">Retry failed pages</span>
					<span class="meta-value">{data.profile.rescrape_failed ? 'Yes' : 'No'}</span>
				</div>
			</div>
		</Card>
	</div>

	<!-- Entrypoints -->
	<div class="mb-4">
		<Card title="Entrypoints ({data.profile.entrypoints.length})" noPadding>
			<div class="ep-list">
				{#each data.profile.entrypoints as ep}
					<div class="ep-row">
						<span class="ep-type type-{ep.type}">{ep.type}</span>
						<span class="mono ep-src">{entrypointLabel(ep)}</span>
						{#if ep.type === 'sitemap' && ep.conflict_resolution}
							<span class="ep-hint">
								last_modified: {ep.conflict_resolution.last_modified} wins,
								language: {ep.conflict_resolution.language} wins
							</span>
						{/if}
					</div>
				{/each}
			</div>
		</Card>
	</div>

	<!-- Discovery -->
	{#if data.profile.discovery?.hosts?.length}
		<div class="mb-4">
			<Card title="Discovery — extra hosts">
				<div class="tag-list">
					{#each data.profile.discovery.hosts as h}
						<span class="tag mono">{h}</span>
					{/each}
				</div>
			</Card>
		</div>
	{/if}

	<!-- Forbidden -->
	{#if data.profile.forbidden}
		<div class="mb-4">
			<Card title="Forbidden">
				{#if data.profile.forbidden.hosts?.length}
					<div class="detail-row">
						<span class="detail-label">Blocked hosts</span>
						<div class="tag-list">
							{#each data.profile.forbidden.hosts as h}
								<span class="tag mono danger-tag">{h}</span>
							{/each}
						</div>
					</div>
				{/if}
				{#if data.profile.forbidden.url_patterns?.length}
					<div class="detail-row">
						<span class="detail-label">URL patterns</span>
						<div class="tag-list">
							{#each data.profile.forbidden.url_patterns as p}
								<span class="tag mono danger-tag">{p}</span>
							{/each}
						</div>
					</div>
				{/if}
			</Card>
		</div>
	{/if}

	<!-- Content extraction -->
	{#if data.profile.content}
		{@const c = data.profile.content}
		{#if (c.content_selectors?.length ?? 0) + (c.noise_phrases?.length ?? 0) + (c.noise_patterns?.length ?? 0) + (c.tag_selectors?.length ?? 0) > 0}
			<div class="mb-4">
				<Card title="Content extraction">
					{#if c.content_selectors?.length}
						<div class="detail-row">
							<span class="detail-label">Content selectors</span>
							<div class="tag-list">{#each c.content_selectors as s}<span class="tag mono">{s}</span>{/each}</div>
						</div>
					{/if}
					{#if c.noise_phrases?.length}
						<div class="detail-row">
							<span class="detail-label">Noise phrases</span>
							<div class="tag-list">{#each c.noise_phrases as p}<span class="tag">{p}</span>{/each}</div>
						</div>
					{/if}
					{#if c.noise_patterns?.length}
						<div class="detail-row">
							<span class="detail-label">Noise patterns</span>
							<div class="tag-list">{#each c.noise_patterns as p}<span class="tag mono">{p}</span>{/each}</div>
						</div>
					{/if}
					{#if c.tag_selectors?.length}
						<div class="detail-row">
							<span class="detail-label">Tag selectors</span>
							<div class="tag-list">{#each c.tag_selectors as s}<span class="tag mono">{s}</span>{/each}</div>
						</div>
					{/if}
				</Card>
			</div>
		{/if}
	{/if}

	<!-- Tasks using this profile -->
	{#if data.tasks.length > 0}
		<div class="mb-4">
			<Card title="Used by tasks" noPadding>
				<TableWrap>
					<table>
						<thead>
							<tr><th>Task</th><th>Type</th><th>Schedule</th></tr>
						</thead>
						<tbody>
							{#each data.tasks as task}
								<tr class="clickable" onclick={() => goto(`${base}/tasks/${task.id}`)}>
									<td>{task.name}</td>
									<td>{task.schedule ? 'Scheduled' : 'Manual'}</td>
									<td class="mono muted">{task.schedule ?? '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</TableWrap>
			</Card>
		</div>
	{/if}

	<!-- Raw JSON accordion -->
	<Card>
		{#snippet children()}
			<button
				class="json-toggle"
				onclick={() => (jsonOpen = !jsonOpen)}
				type="button"
			>
				<span class="json-toggle-title">Raw JSON configuration</span>
				<span class="chevron">{jsonOpen ? '▾' : '▸'}</span>
			</button>
			{#if jsonOpen}
				<pre class="mono-block">{profileJson}</pre>
			{/if}
		{/snippet}
	</Card>
</PageContent>

<ConfirmDialog
	open={confirmDelete}
	title="Delete profile?"
	message="Are you sure you want to delete '{data.profile.name}'? This cannot be undone."
	confirmLabel="Delete profile"
	danger
	onConfirm={handleDelete}
	onCancel={() => (confirmDelete = false)}
/>

<style>
	.mb-4 { margin-bottom: 16px; }
	.mono { font-family: var(--font-mono); font-size: 0.9em; }
	.muted { color: var(--c-text-muted); }

	.meta-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: 16px;
	}

	.meta-item { display: flex; flex-direction: column; gap: 3px; }

	.meta-label {
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--c-text-muted);
	}

	.meta-value { font-size: 13px; color: var(--c-text); }

	.ep-list { padding: 0 18px; }

	.ep-row {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 0;
		border-bottom: 1px solid var(--c-border-subtle);
	}

	.ep-row:last-child { border-bottom: none; }

	.ep-type {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		padding: 2px 7px;
		border-radius: 100px;
		flex-shrink: 0;
	}

	.type-host { background: #dbeafe; color: #1d4ed8; }
	.type-sitemap { background: #d1fae5; color: #065f46; }

	.ep-src { font-size: 13px; color: var(--c-text); flex: 1; }
	.ep-hint { font-size: 11px; color: var(--c-text-muted); }

	.detail-row {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 8px 0;
		border-bottom: 1px solid var(--c-border-subtle);
	}

	.detail-row:last-child { border-bottom: none; }

	.detail-label {
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--c-text-muted);
	}

	.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }

	.tag {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		background: var(--c-border-subtle);
		border: 1px solid var(--c-border);
		border-radius: 100px;
		font-size: 12px;
		color: var(--c-text-secondary);
	}

	.danger-tag {
		background: var(--c-danger-light);
		border-color: #fecaca;
		color: #991b1b;
	}

	.json-toggle {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		background: none;
		border: none;
		cursor: pointer;
		padding: 0;
		text-align: left;
	}

	.json-toggle:hover .json-toggle-title { color: var(--c-primary); }

	.json-toggle-title {
		font-size: 13px;
		font-weight: 600;
		color: var(--c-text);
	}

	.chevron { font-size: 12px; color: var(--c-text-muted); }

	.mono-block {
		font-family: var(--font-mono);
		font-size: 12px;
		background: #0f172a;
		color: #e2e8f0;
		border-radius: var(--radius);
		padding: 14px 16px;
		overflow-x: auto;
		white-space: pre;
		line-height: 1.6;
		margin-top: 12px;
	}
</style>
