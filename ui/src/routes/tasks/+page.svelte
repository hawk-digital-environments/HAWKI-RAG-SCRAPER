<script lang="ts">
	import type { PageData } from './$types';
	import Badge from '$lib/ui/Badge.svelte';
	import Button from '$lib/ui/Button.svelte';
	import Card from '$lib/ui/Card.svelte';
	import TableWrap from '$lib/ui/TableWrap.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import EmptyState from '$lib/ui/EmptyState.svelte';
	import { startJob } from '$lib/api';
	import cronstrue from 'cronstrue';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';

	let { data }: { data: PageData } = $props();

	let startingTaskId = $state<string | null>(null);

	const profileMap = $derived(new Map(data.profiles.map((p) => [p.id, p])));

	async function handleStartTask(taskId: string) {
		startingTaskId = taskId;
		try {
			const job = await startJob(taskId);
			await goto(`${base}/jobs/${job.id}`);
		} finally {
			startingTaskId = null;
		}
	}

	function cronHuman(expr: string): string {
		try {
			return cronstrue.toString(expr);
		} catch {
			return expr;
		}
	}
</script>

<svelte:head><title>Tasks — RAG Interface</title></svelte:head>

<PageContent
	title="Tasks"
	subtitle="A task links a scraping profile to a schedule (or lets you trigger it manually). Each run creates a new job. Manual tasks have a Start button; scheduled tasks run automatically at the given cron time."
>
	{#snippet actions()}
		<Button variant="primary" size="sm" href="{base}/tasks/new">+ New Task</Button>
	{/snippet}

	{#if data.tasks.length === 0}
		<Card>
			<EmptyState>
				No tasks yet. <a href="{base}/tasks/new">Create a task</a> to schedule or manually trigger profile runs.
			</EmptyState>
		</Card>
	{:else}
		<Card noPadding>
			<TableWrap>
				<table>
					<thead>
						<tr>
							<th>Name</th>
							<th>Profile</th>
							<th>Type</th>
							<th>Schedule</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each data.tasks as task}
							{@const profile = profileMap.get(task.profileId)}
							<tr class="clickable" onclick={() => goto(`${base}/tasks/${task.id}`)}>
								<td><strong>{task.name}</strong></td>
								<td>{profile?.name ?? task.profileId}</td>
								<td>
									<Badge
										status={task.schedule ? 'scheduled' : 'manual'}
										label={task.schedule ? 'Scheduled' : 'Manual'}
									/>
								</td>
								<td class="muted mono">{task.schedule ? cronHuman(task.schedule) : '—'}</td>
								<td class="action-cell">
									{#if !task.schedule}
										<Button
											variant="secondary"
											size="sm"
											title="Start now"
											disabled={startingTaskId === task.id}
											onclick={(e) => { e.stopPropagation(); handleStartTask(task.id); }}
										>
											▶ Start
										</Button>
									{/if}
								</td>
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

	.action-cell {
		text-align: right;
		white-space: nowrap;
	}
</style>
