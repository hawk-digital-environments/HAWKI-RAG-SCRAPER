<script lang="ts">
	import type { PageData } from './$types';
	import Badge from '$lib/ui/Badge.svelte';
	import Button from '$lib/ui/Button.svelte';
	import Card from '$lib/ui/Card.svelte';
	import TableWrap from '$lib/ui/TableWrap.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import Breadcrumb from '$lib/ui/Breadcrumb.svelte';
	import EmptyState from '$lib/ui/EmptyState.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import { startJob, deleteTask } from '$lib/api';
	import cronstrue from 'cronstrue';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';

	let { data }: { data: PageData } = $props();

	let confirmDelete = $state(false);

	function formatDate(iso: string) {
		return new Date(iso).toLocaleString('en-GB', {
			day: '2-digit', month: 'short', year: 'numeric',
			hour: '2-digit', minute: '2-digit'
		});
	}

	function cronHuman(expr: string): string {
		try {
			return cronstrue.toString(expr);
		} catch {
			return expr;
		}
	}

	async function handleStartNow() {
		const job = await startJob(data.task.id);
		await goto(`${base}/jobs/${job.id}`);
	}

	async function handleDelete() {
		await deleteTask(data.task.id);
		await goto(`${base}/tasks`);
	}
</script>

<svelte:head><title>{data.task.name} — RAG Interface</title></svelte:head>

<PageContent title={data.task.name}>
	{#snippet breadcrumb()}
		<Breadcrumb items={[{ label: 'Tasks', href: `${base}/tasks` }, { label: data.task.name }]} />
	{/snippet}
	{#snippet actions()}
		<Button variant="primary" onclick={handleStartNow}>▶ Start now</Button>
		<Button variant="secondary" href="{base}/tasks/{data.task.id}/edit">✎ Modify</Button>
		<Button variant="danger" onclick={() => (confirmDelete = true)}>Delete</Button>
	{/snippet}

	<div class="mb-4">
		<Card>
			<div class="meta-grid">
				<div class="meta-item">
					<span class="meta-label">Type</span>
					<span class="meta-value">
						<Badge
							status={data.task.schedule ? 'scheduled' : 'manual'}
							label={data.task.schedule ? 'Scheduled' : 'Manual'}
						/>
					</span>
				</div>
				<div class="meta-item">
					<span class="meta-label">Profile</span>
					<span class="meta-value">
						{#if data.profile}
							<a href="{base}/profiles/{data.profile.id}">{data.profile.name}</a>
						{:else}
							<span class="muted">{data.task.profileId}</span>
						{/if}
					</span>
				</div>
				{#if data.task.schedule}
					<div class="meta-item">
						<span class="meta-label">Schedule</span>
						<span class="meta-value mono">{data.task.schedule}</span>
					</div>
					<div class="meta-item">
						<span class="meta-label">Schedule (human)</span>
						<span class="meta-value">{cronHuman(data.task.schedule)}</span>
					</div>
				{/if}
				{#if data.profile}
					<div class="meta-item">
						<span class="meta-label">Max execution</span>
						<span class="meta-value mono">{data.profile.max_execution_time}</span>
					</div>
					<div class="meta-item">
						<span class="meta-label">Max storage</span>
						<span class="meta-value mono">{data.profile.max_storage_time}</span>
					</div>
				{/if}
			</div>
		</Card>
	</div>

	<Card title="Recent jobs" noPadding>
		{#if data.recentJobs.length === 0}
			<EmptyState>No jobs have been run for this task yet.</EmptyState>
		{:else}
			<TableWrap>
				<table>
					<thead>
						<tr>
							<th>Job ID</th>
							<th>Status</th>
							<th>Started</th>
							<th>Finished</th>
						</tr>
					</thead>
					<tbody>
						{#each data.recentJobs as job}
							<tr class="clickable" onclick={() => goto(`${base}/jobs/${job.id}`)}>
								<td class="mono">{job.id}</td>
								<td><Badge status={job.status} /></td>
								<td class="muted">{formatDate(job.startTime)}</td>
								<td class="muted">{job.endTime ? formatDate(job.endTime) : '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</TableWrap>
		{/if}
	</Card>
</PageContent>

<ConfirmDialog
	open={confirmDelete}
	title="Delete task?"
	message="Are you sure you want to delete the task '{data.task.name}'? This cannot be undone."
	confirmLabel="Delete task"
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
</style>
