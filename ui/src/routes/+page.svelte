<script lang="ts">
    import type {PageData} from './$types';
    import Badge from '$lib/ui/Badge.svelte';
    import Card from '$lib/ui/Card.svelte';
    import TableWrap from '$lib/ui/TableWrap.svelte';
    import PageContent from '$lib/ui/PageContent.svelte';
    import EmptyState from '$lib/ui/EmptyState.svelte';
    import {goto} from '$app/navigation';
    import { base } from '$app/paths';

    let {data}: { data: PageData } = $props();

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
</script>

<svelte:head><title>Running Jobs — RAG Interface</title></svelte:head>

<PageContent
    title="Running Jobs"
    subtitle="Jobs that are currently executing or being stopped. Click a row to view live logs and controls."
>
    <div class="mb-6">
        {#if data.runningJobs.length === 0}
            <Card>
                <EmptyState>
                    No jobs currently running. Start a task from the <a href="{base}/tasks">Tasks</a> page.
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
                            <th>Status</th>
                        </tr>
                        </thead>
                        <tbody>
                        {#each data.runningJobs as job}
                            {@const task = taskMap.get(job.taskId)}
                            {@const profile = profileMap.get(job.profileId)}
                            <tr class="clickable" onclick={() => goto(`${base}/jobs/${job.id}`)}>
                                <td class="mono">{job.id}</td>
                                <td>{profile?.name ?? job.profileId}</td>
                                <td>{task?.name ?? job.taskId}</td>
                                <td class="muted">{formatRelative(job.startTime)}</td>
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

    .mono {
        font-family: var(--font-mono);
        font-size: 0.9em;
    }

    .muted {
        color: var(--c-text-muted);
    }

</style>
