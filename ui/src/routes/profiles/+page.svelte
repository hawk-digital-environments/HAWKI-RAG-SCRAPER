<script lang="ts">
	import type { PageData } from './$types';
	import Button from '$lib/ui/Button.svelte';
	import Card from '$lib/ui/Card.svelte';
	import TableWrap from '$lib/ui/TableWrap.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import EmptyState from '$lib/ui/EmptyState.svelte';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';

	let { data }: { data: PageData } = $props();
</script>

<svelte:head><title>Profiles — RAG Interface</title></svelte:head>

<PageContent
	title="Profiles"
	subtitle="A profile defines what the crawler scrapes and how: which URLs to start from, which hosts to skip, how to extract content, and how long to keep the results. Profiles are reusable — multiple tasks can share the same one."
>
	{#snippet actions()}
		<Button variant="primary" size="sm" href="{base}/profiles/new">+ New Profile</Button>
	{/snippet}

	{#if data.profiles.length === 0}
		<Card>
			<EmptyState>
				No profiles yet. <a href="{base}/profiles/new">Create a profile</a> to define a scraping configuration.
			</EmptyState>
		</Card>
	{:else}
		<Card noPadding>
			<TableWrap>
				<table>
					<thead>
						<tr>
							<th>Name</th>
							<th>Entrypoints</th>
							<th>Max execution</th>
							<th>Max storage</th>
							<th>Retry failed</th>
						</tr>
					</thead>
					<tbody>
						{#each data.profiles as profile}
							<tr class="clickable" onclick={() => goto(`${base}/profiles/${profile.id}`)}>
								<td><strong>{profile.name}</strong></td>
								<td class="muted">
									{profile.entrypoints.length} entrypoint{profile.entrypoints.length !== 1 ? 's' : ''}
								</td>
								<td class="mono muted">{profile.max_execution_time}</td>
								<td class="mono muted">{profile.max_storage_time}</td>
								<td>{profile.rescrape_failed ? '✓' : '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</TableWrap>
		</Card>
	{/if}
</PageContent>

<style>
	.muted { color: var(--c-text-muted); }
	.mono { font-family: var(--font-mono); font-size: 0.9em; }
</style>
