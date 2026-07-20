<script lang="ts">
	import { untrack } from 'svelte';
	import type { PageData } from './$types';
	import type { Profile } from '$lib/api/types';
	import Button from '$lib/ui/Button.svelte';
	import Card from '$lib/ui/Card.svelte';
	import TableWrap from '$lib/ui/TableWrap.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import EmptyState from '$lib/ui/EmptyState.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import { deleteProfile, getAllProfiles } from '$lib/api';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';

	let { data }: { data: PageData } = $props();
	const initialData = untrack(() => data);
	let profiles = $state<Profile[]>([...initialData.profiles]);
	let profileToRemove = $state<Profile | undefined>(undefined);
	let removingProfile = $state<string | undefined>(undefined);
	let removeError = $state('');

	async function refreshProfiles() {
		profiles = await getAllProfiles();
	}

	async function confirmRemoveProfile() {
		if (!profileToRemove) return;
		const target = profileToRemove;
		profileToRemove = undefined;
		removingProfile = target.id;
		removeError = '';
		try {
			await deleteProfile(target.id);
			await refreshProfiles();
		} catch (error) {
			removeError = error instanceof Error ? error.message : 'Failed to remove profile';
		} finally {
			removingProfile = undefined;
		}
	}
</script>

<svelte:head><title>Profiles — RAG Interface</title></svelte:head>

<PageContent
	title="Profiles"
	subtitle="A profile defines what the crawler scrapes and how: which URLs to start from, which hosts to skip, how to extract content, and how long to keep the results. Profiles are reusable — multiple tasks can share the same one."
>
	{#snippet actions()}
		<Button variant="primary" size="sm" href="{base}/profiles/new">+ New Profile</Button>
	{/snippet}

	{#if profiles.length === 0}
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
							<th class="action-col"></th>
						</tr>
					</thead>
					<tbody>
						{#each profiles as profile}
							<tr class="clickable" onclick={() => goto(`${base}/profiles/${profile.id}`)}>
								<td><strong>{profile.name}</strong></td>
								<td class="muted">
									{profile.entrypoints.length} entrypoint{profile.entrypoints.length !== 1 ? 's' : ''}
								</td>
								<td class="mono muted">{profile.max_execution_time}</td>
								<td class="mono muted">{profile.max_storage_time}</td>
								<td>{profile.rescrape_failed ? '✓' : '—'}</td>
								<td class="action-col">
									<Button
										variant="danger"
										size="sm"
										disabled={profile.readonlyExample || removingProfile === profile.id}
										title={profile.readonlyExample ? 'Readonly example profile cannot be removed' : 'Remove profile'}
										onclick={(event) => {
											event.stopPropagation();
											profileToRemove = profile;
										}}
									>
										{removingProfile === profile.id ? 'Removing...' : 'Remove'}
									</Button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</TableWrap>
		</Card>
		{#if removeError}
			<p class="error-text">{removeError}</p>
		{/if}
	{/if}
</PageContent>

<ConfirmDialog
	open={!!profileToRemove}
	title="Remove profile?"
	message={`Remove ${profileToRemove?.name ?? 'this profile'}? This deletes the profile JSON file and cannot be undone.`}
	confirmLabel="Remove"
	danger
	onConfirm={confirmRemoveProfile}
	onCancel={() => (profileToRemove = undefined)}
/>

<style>
	.muted { color: var(--c-text-muted); }
	.mono { font-family: var(--font-mono); font-size: 0.9em; }
	.action-col {
		text-align: right;
		width: 1%;
		white-space: nowrap;
	}
	.error-text {
		margin: 8px 0 0;
		color: var(--c-danger);
		font-size: 13px;
	}
</style>
