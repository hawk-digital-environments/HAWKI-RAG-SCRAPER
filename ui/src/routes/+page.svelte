<script lang="ts">
    import { untrack } from 'svelte';
    import type {PageData} from './$types';
    import Badge from '$lib/ui/Badge.svelte';
    import Button from '$lib/ui/Button.svelte';
    import Card from '$lib/ui/Card.svelte';
    import TableWrap from '$lib/ui/TableWrap.svelte';
    import PageContent from '$lib/ui/PageContent.svelte';
    import EmptyState from '$lib/ui/EmptyState.svelte';
    import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
    import { deleteQueue, getQueues, purgeQueue } from '$lib/api';
    import type { Queue } from '$lib/api/types';
    import {goto} from '$app/navigation';
    import { base } from '$app/paths';

    let {data}: { data: PageData } = $props();
    const initialData = untrack(() => data);

    let queuesOpen = $state(false);
    let queues = $state<Queue[]>([...initialData.queues]);
    let queueToPurge = $state<Queue | undefined>(undefined);
    let purgingQueue = $state<string | undefined>(undefined);
    let queueError = $state('');

    const protectedQueueNames = new Set([
        'crawl_jobs',
        'crawl_jobs_retry',
        'failed_jobs',
        'rag_ingestion_failed_jobs',
        'rag_ingestion_jobs',
        'rag_ingestion_jobs_retry'
    ]);

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

    async function refreshQueues() {
        queues = await getQueues();
    }

    async function confirmPurgeQueue() {
        if (!queueToPurge) return;
        const target = queueToPurge;
        queueToPurge = undefined;
        if (protectedQueueNames.has(target.name)) {
            queueError = `${target.name} is a default system queue and cannot be removed from the UI.`;
            return;
        }
        purgingQueue = target.name;
        queueError = '';
        try {
            if (target.ready > 0) {
                await purgeQueue(target.name, target.vhost ?? '/');
            }
            await deleteQueue(target.name, target.vhost ?? '/');
            queues = queues.filter((queue) => queue.name !== target.name || queue.vhost !== target.vhost);
            await refreshQueues();
        } catch (error) {
            await refreshQueues();
            queueError =
                target.unacked > 0
                    ? 'Ready messages were removed, but RabbitMQ cannot delete a queue while messages are unacked. Stop the consumer or wait until they are requeued, then remove again.'
                    : error instanceof Error ? error.message : 'Failed to remove queue';
        } finally {
            purgingQueue = undefined;
        }
    }
</script>

<svelte:head><title>Running Jobs — RAG Interface</title></svelte:head>

<PageContent
    title="Running Jobs"
    subtitle="Jobs that are currently executing or being stopped. Click a row to view live logs and controls."
>
    <!-- Running Jobs -->
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

    <!-- Queues -->
    <div>
        <Button variant="ghost" onclick={() => (queuesOpen = !queuesOpen)} type="button">
            {queuesOpen ? '▾' : '▸'} Queues (RabbitMQ)
        </Button>

        {#if queuesOpen}
            <div class="mt-2">
                <Card noPadding>
                    <TableWrap>
                        <table>
                            <thead>
                            <tr>
                                <th>Name</th>
                                <th class="number">Ready</th>
                                <th class="number">Unacked</th>
                                <th class="number">Total</th>
                                <th class="action-col"></th>
                            </tr>
                            </thead>
                            <tbody>
                            {#each queues as q}
                                {@const isProtectedQueue = protectedQueueNames.has(q.name)}
                                <tr>
                                    <td class="mono">{q.name}</td>
                                    <td class="number">{q.ready}</td>
                                    <td class="number" class:busy={q.unacked > 0}>{q.unacked}</td>
                                    <td class="number total-col">{q.total}</td>
                                    <td class="action-col">
                                        <Button
                                            variant="danger"
                                            size="sm"
                                            disabled={isProtectedQueue || purgingQueue === q.name}
                                            title={isProtectedQueue ? 'Default system queue; cannot be removed here' : 'Remove ready messages and delete the queue if it is empty'}
                                            onclick={() => (queueToPurge = q)}
                                        >
                                            {purgingQueue === q.name ? 'Removing...' : 'Remove'}
                                        </Button>
                                    </td>
                                </tr>
                            {/each}
                            </tbody>
                        </table>
                    </TableWrap>
                </Card>
                {#if queueError}
                    <p class="error-text">{queueError}</p>
                {/if}
            </div>
        {/if}
    </div>
</PageContent>

<ConfirmDialog
    open={!!queueToPurge}
    title="Remove queue?"
    message={`This removes ${queueToPurge?.ready ?? 0} ready message${(queueToPurge?.ready ?? 0) === 1 ? '' : 's'} from ${queueToPurge?.name ?? 'this queue'}, then deletes the queue if it is empty. Unacked messages cannot be removed until RabbitMQ requeues them.`}
    confirmLabel="Remove"
    danger
    onConfirm={confirmPurgeQueue}
    onCancel={() => (queueToPurge = undefined)}
/>

<style>
    .mb-6 {
        margin-bottom: 24px;
    }

    .mt-2 {
        margin-top: 8px;
    }

    .mono {
        font-family: var(--font-mono);
        font-size: 0.9em;
    }

    .muted {
        color: var(--c-text-muted);
    }

    .number {
        text-align: right;
    }

    .busy {
        color: var(--c-warning);
        font-weight: 600;
    }

    .total-col {
        font-weight: 600;
    }

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
