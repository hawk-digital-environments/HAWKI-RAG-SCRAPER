<script lang="ts">
	import type { PageData } from './$types';
	import type { Job } from '$lib/api/types';
	import Badge from '$lib/ui/Badge.svelte';
	import Button from '$lib/ui/Button.svelte';
	import Card from '$lib/ui/Card.svelte';
	import Alert from '$lib/ui/Alert.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import Breadcrumb from '$lib/ui/Breadcrumb.svelte';
	import TableWrap from '$lib/ui/TableWrap.svelte';
	import { getJob, stopJob, finalizeStopJob, retryJob, restartJob } from '$lib/api';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';

	let { data }: { data: PageData } = $props();

	let job = $state<Job>({ ...data.job });

	const isRunning = $derived(job.status === 'running');
	const isStopping = $derived(job.status === 'stopping');
	const isTerminal = $derived(['completed', 'failed', 'cancelled'].includes(job.status));
	const hasFailedPages = $derived((job.failedPages?.length ?? 0) > 0);
	const isCompleteFailure = $derived(job.status === 'failed');

	function formatDate(iso: string) {
		return new Date(iso).toLocaleString('en-GB', {
			day: '2-digit', month: 'short', year: 'numeric',
			hour: '2-digit', minute: '2-digit', second: '2-digit'
		});
	}

	function duration(start: string, end?: string) {
		const ms = new Date(end ?? Date.now()).getTime() - new Date(start).getTime();
		const totalSecs = Math.floor(ms / 1000);
		const hrs = Math.floor(totalSecs / 3600);
		const mins = Math.floor((totalSecs % 3600) / 60);
		const secs = totalSecs % 60;
		if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
		if (mins > 0) return `${mins}m ${secs}s`;
		return `${secs}s`;
	}

	function getLogClass(line: string): string {
		if (line.includes(' FATAL ') || line.includes('FATAL')) return 'log-line-fatal';
		if (line.includes(' ERROR ') || line.includes('Error') || line.includes('error')) return 'log-line-error';
		if (line.includes(' WARN ') || line.includes('Warning')) return 'log-line-warn';
		return '';
	}

	let logEl = $state<HTMLDivElement | undefined>(undefined);

	$effect(() => {
		job.log;
		if (logEl) logEl.scrollTop = logEl.scrollHeight;
	});

	let pollInterval: ReturnType<typeof setInterval> | undefined;
	$effect(() => {
		if (job.status === 'running') {
			pollInterval = setInterval(async () => {
				const updated = await getJob(job.id);
				if (updated) job = { ...updated };
			}, 5000);
		} else {
			clearInterval(pollInterval);
		}
		return () => clearInterval(pollInterval);
	});

	async function handleStop() {
		const updated = await stopJob(job.id);
		if (updated) {
			job = { ...updated };
			setTimeout(async () => {
				const finalized = await finalizeStopJob(job.id);
				if (finalized) job = { ...finalized };
			}, 2000);
		}
	}

	async function handleRetry() {
		const newJob = await retryJob(job.id);
		await goto(`${base}/jobs/${newJob.id}`);
	}

	async function handleRestart() {
		const newJob = await restartJob(job.id);
		await goto(`${base}/jobs/${newJob.id}`);
	}
</script>

<svelte:head><title>Job {job.id} — RAG Interface</title></svelte:head>

<PageContent title="Job {job.id}" subtitle={data.task ? `Task: ${data.task.name}` : undefined}>
	{#snippet breadcrumb()}
		<Breadcrumb items={[{ label: 'Running Jobs', href: `${base}/` }, { label: 'Job details' }]} />
	{/snippet}
	{#snippet actions()}
		{#if isRunning}
			<Button variant="danger" onclick={handleStop}>⏹ Stop job</Button>
		{/if}
		{#if isStopping}
			<Button variant="danger" disabled>⏹ Stopping…</Button>
		{/if}
	{/snippet}

	<!-- Status callouts -->
	{#if isCompleteFailure}
		<div class="mb-4">
			<Alert variant="danger">
				<strong>Job failed entirely.</strong> The runner process crashed before completing. You can
				restart this job to try again from scratch.
				<div class="mt-2">
					<Button variant="secondary" size="sm" onclick={handleRestart}>↺ Restart job</Button>
				</div>
			</Alert>
		</div>
	{/if}

	{#if job.status === 'completed' && hasFailedPages}
		<div class="mb-4">
			<Alert variant="warning">
				<strong>{job.failedPages?.length} page{(job.failedPages?.length ?? 0) > 1 ? 's' : ''} failed to scrape</strong>
				during this job. The rest completed successfully.
				{#if !job.dataExpired}
					<div class="mt-2">
						<Button variant="secondary" size="sm" onclick={handleRetry}>↺ Retry failed pages</Button>
					</div>
				{:else}
					<p class="expired-note">Cannot retry: job data has been deleted (max_storage_time exceeded).</p>
				{/if}
			</Alert>
		</div>
	{/if}

	{#if job.status === 'completed' && !hasFailedPages}
		<div class="mb-4">
			<Alert variant="success">
				Job completed successfully.
			</Alert>
		</div>
	{/if}

	<!-- Meta grid -->
	<div class="mb-4">
		<Card>
			<div class="meta-grid">
				<div class="meta-item">
					<span class="meta-label">Status</span>
					<span class="meta-value"><Badge status={job.status} /></span>
				</div>
				<div class="meta-item">
					<span class="meta-label">Profile</span>
					<span class="meta-value">
						{#if data.profile}
							<a href="{base}/profiles/{data.profile.id}">{data.profile.name}</a>
						{:else}{job.profileId}{/if}
					</span>
				</div>
				<div class="meta-item">
					<span class="meta-label">Task</span>
					<span class="meta-value">
						{#if data.task}
							<a href="{base}/tasks/{data.task.id}">{data.task.name}</a>
						{:else}{job.taskId}{/if}
					</span>
				</div>
				<div class="meta-item">
					<span class="meta-label">Started</span>
					<span class="meta-value">{formatDate(job.startTime)}</span>
				</div>
				{#if job.endTime}
					<div class="meta-item">
						<span class="meta-label">Finished</span>
						<span class="meta-value">{formatDate(job.endTime)}</span>
					</div>
					<div class="meta-item">
						<span class="meta-label">Duration</span>
						<span class="meta-value mono">{duration(job.startTime, job.endTime)}</span>
					</div>
				{:else}
					<div class="meta-item">
						<span class="meta-label">Running for</span>
						<span class="meta-value mono">{duration(job.startTime)}</span>
					</div>
				{/if}
			</div>
		</Card>
	</div>

	<!-- Failed pages list -->
	{#if hasFailedPages && isTerminal}
		<div class="mb-4">
			<Card title="Failed pages ({job.failedPages?.length})">
				<ul class="failed-list">
					{#each job.failedPages ?? [] as url}
						<li class="mono">{url}</li>
					{/each}
				</ul>
			</Card>
		</div>
	{/if}

	<!-- Log output -->
	<Card title="Log output" noPadding>
		{#snippet actions()}
			{#if isRunning}
				<span class="live-indicator">● Live</span>
			{/if}
		{/snippet}
		{#snippet children()}
			<div class="log-block" bind:this={logEl}>
				{#each job.log as line}
					<div class={getLogClass(line)}>{line}</div>
				{/each}
				{#if isRunning || isStopping}
					<div class="log-cursor">▌</div>
				{/if}
			</div>
		{/snippet}
	</Card>
</PageContent>

<style>
	.mb-4 { margin-bottom: 16px; }
	.mt-2 { margin-top: 8px; }

	.mono { font-family: var(--font-mono); font-size: 0.9em; }

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

	.failed-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.failed-list li {
		font-size: 12px;
		color: var(--c-danger);
		padding: 4px 8px;
		background: var(--c-danger-light);
		border-radius: var(--radius-sm);
	}

	.expired-note {
		margin-top: 6px;
		font-size: 12px;
		color: var(--c-text-muted);
	}

	.live-indicator {
		font-size: 11px;
		font-weight: 600;
		color: var(--c-success);
		animation: pulse 2s infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	.log-block {
		font-family: var(--font-mono);
		font-size: 12px;
		background: #0f172a;
		color: #e2e8f0;
		border-radius: 0 0 var(--radius-lg) var(--radius-lg);
		padding: 14px 16px;
		overflow-y: auto;
		max-height: 420px;
		white-space: pre-wrap;
		word-break: break-all;
		line-height: 1.7;
	}

	.log-cursor { animation: blink 1s step-end infinite; color: var(--c-success); }
	@keyframes blink { 50% { opacity: 0; } }

	:global(.log-line-warn) { color: #fbbf24; }
	:global(.log-line-error) { color: #f87171; }
	:global(.log-line-fatal) { color: #ef4444; font-weight: 600; }
</style>
