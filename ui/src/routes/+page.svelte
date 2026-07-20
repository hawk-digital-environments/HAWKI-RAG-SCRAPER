<script lang="ts">
    import { onMount, untrack } from 'svelte';
    import type {PageData} from './$types';
    import type { Job } from '$lib/api/types';
    import Badge from '$lib/ui/Badge.svelte';
    import Card from '$lib/ui/Card.svelte';
    import TableWrap from '$lib/ui/TableWrap.svelte';
    import PageContent from '$lib/ui/PageContent.svelte';
    import EmptyState from '$lib/ui/EmptyState.svelte';
    import Alert from '$lib/ui/Alert.svelte';
    import {goto} from '$app/navigation';
    import { base } from '$app/paths';
    import { getDashboardJobs } from '$lib/api';

    let {data}: { data: PageData } = $props();
    const initialData = untrack(() => data);

    let jobs = $state<Job[]>(initialData.jobs);
    let refreshError = $state<string | null>(initialData.jobsError);
    let isRefreshing = $state(false);

    const profileMap = $derived(new Map(data.profiles.map((p) => [p.id, p])));
    const taskMap = $derived(new Map(data.tasks.map((t) => [t.id, t])));

    function formatRelative(iso: string) {
        const diff = Date.now() - new Date(iso).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        return `${Math.floor(hrs / 24)}d ago`;
    }

    async function refreshJobs() {
        if (isRefreshing) return;
        isRefreshing = true;
        try {
            jobs = await getDashboardJobs();
            refreshError = null;
        } catch (error) {
            refreshError = error instanceof Error ? error.message : 'Failed to refresh jobs';
        } finally {
            isRefreshing = false;
        }
    }

    onMount(() => {
        void refreshJobs();
        const interval = window.setInterval(() => void refreshJobs(), 3000);
        return () => window.clearInterval(interval);
    });
</script>

<svelte:head><title>Jobs — RAG Interface</title></svelte:head>

<PageContent
    title="Jobs"
    subtitle="Active jobs and latest results. Click a row to view live logs, controls, and the saved result summary."
>
    <div class="mb-6">
        {#if refreshError}
            <div class="mb-4">
                <Alert variant="danger">
                    {refreshError}
                </Alert>
            </div>
        {/if}

        {#if jobs.length === 0}
            <Card>
                <EmptyState>
                    No jobs have been submitted yet. Start a task from the <a href="{base}/tasks">Tasks</a> page.
                </EmptyState>
            </Card>
        {:else}
            <Card noPadding>
                <TableWrap>
                    <table>
                        <thead>
                        <tr>
                            <th>Job ID</th>
                            <th>Profile</th>
                            <th>Task</th>
                            <th>Started</th>
                            <th>Finished</th>
                            <th>Status</th>
                        </tr>
                        </thead>
                        <tbody>
                        {#each jobs as job}
                            {@const task = taskMap.get(job.taskId)}
                            {@const profile = profileMap.get(job.profileId)}
                            <tr class="clickable" onclick={() => goto(`${base}/jobs/${job.id}`)}>
                                <td class="mono">{job.id}</td>
                                <td>{profile?.name ?? job.profileId}</td>
                                <td>{task?.name ?? job.taskId}</td>
                                <td class="muted">{formatRelative(job.startTime)}</td>
                                <td class="muted">{job.endTime ? formatRelative(job.endTime) : '—'}</td>
                                <td>
                                    <Badge status={job.status}/>
                                </td>
                            </tr>
                        {/each}
                        </tbody>
                    </table>
                </TableWrap>
            </Card>
        {/if}
    </div>

</PageContent>

<style>
    .mb-6 {
        margin-bottom: 24px;
    }

    .mb-4 {
        margin-bottom: 16px;
    }

    .mono {
        font-family: var(--font-mono);
        font-size: 0.9em;
    }

    .muted {
        color: var(--c-text-muted);
    }

</style>
