<script lang="ts">
	import type { PageData } from './$types';
	import TaskForm from '$lib/components/TaskForm.svelte';
	import Card from '$lib/ui/Card.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import Breadcrumb from '$lib/ui/Breadcrumb.svelte';
	import { createTask } from '$lib/api';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import type { TaskInput } from '$lib/api/types';

	let { data }: { data: PageData } = $props();

	async function handleSubmit(input: TaskInput) {
		const task = await createTask(input);
		await goto(`${base}/tasks/${task.id}`);
	}
</script>

<svelte:head><title>New Task — RAG Interface</title></svelte:head>

<PageContent title="Create task">
	{#snippet breadcrumb()}
		<Breadcrumb items={[{ label: 'Tasks', href: `${base}/tasks` }, { label: 'New task' }]} />
	{/snippet}

	<Card>
		<TaskForm
			profiles={data.profiles}
			initialData={{ profileId: data.preselectedProfileId }}
			submitLabel="Create task"
			onSubmit={handleSubmit}
		/>
	</Card>
</PageContent>
