<script lang="ts">
	import type { PageData } from './$types';
	import TaskForm from '$lib/components/TaskForm.svelte';
	import Card from '$lib/ui/Card.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import Breadcrumb from '$lib/ui/Breadcrumb.svelte';
	import { updateTask } from '$lib/api';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import type { TaskInput } from '$lib/api/types';

	let { data }: { data: PageData } = $props();

	async function handleSubmit(input: TaskInput) {
		await updateTask(data.task.id, input);
		await goto(`${base}/tasks/${data.task.id}`);
	}
</script>

<svelte:head><title>Edit {data.task.name} — RAG Interface</title></svelte:head>

<PageContent title="Modify task">
	{#snippet breadcrumb()}
		<Breadcrumb items={[
			{ label: 'Tasks', href: `${base}/tasks` },
			{ label: data.task.name, href: `${base}/tasks/${data.task.id}` },
			{ label: 'Edit' }
		]} />
	{/snippet}

	<Card>
		<TaskForm
			profiles={data.profiles}
			initialData={data.task}
			submitLabel="Save changes"
			onSubmit={handleSubmit}
		/>
	</Card>
</PageContent>
