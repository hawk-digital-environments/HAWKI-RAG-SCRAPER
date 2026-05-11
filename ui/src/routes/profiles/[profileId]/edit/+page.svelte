<script lang="ts">
	import type { PageData } from './$types';
	import ProfileForm from '$lib/components/ProfileForm.svelte';
	import Card from '$lib/ui/Card.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import Breadcrumb from '$lib/ui/Breadcrumb.svelte';
	import { updateProfile } from '$lib/api';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import type { ProfileInput } from '$lib/api/types';

	let { data }: { data: PageData } = $props();

	async function handleSubmit(input: ProfileInput) {
		await updateProfile(data.profile.id, input);
		await goto(`${base}/profiles/${data.profile.id}`);
	}
</script>

<svelte:head><title>Edit {data.profile.name} — RAG Interface</title></svelte:head>

<PageContent title="Modify profile">
	{#snippet breadcrumb()}
		<Breadcrumb items={[
			{ label: 'Profiles', href: `${base}/profiles` },
			{ label: data.profile.name, href: `${base}/profiles/${data.profile.id}` },
			{ label: 'Edit' }
		]} />
	{/snippet}

	<Card>
		<ProfileForm
			initialData={data.profile}
			submitLabel="Save changes"
			onSubmit={handleSubmit}
		/>
	</Card>
</PageContent>
