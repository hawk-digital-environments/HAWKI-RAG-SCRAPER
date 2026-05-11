<script lang="ts">
	import ProfileForm from '$lib/components/ProfileForm.svelte';
	import Card from '$lib/ui/Card.svelte';
	import PageContent from '$lib/ui/PageContent.svelte';
	import Breadcrumb from '$lib/ui/Breadcrumb.svelte';
	import { createProfile } from '$lib/api';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import type { ProfileInput } from '$lib/api/types';

	async function handleSubmit(input: ProfileInput) {
		const profile = await createProfile(input);
		await goto(`${base}/profiles/${profile.id}`);
	}
</script>

<svelte:head><title>New Profile — RAG Interface</title></svelte:head>

<PageContent title="Create profile">
	{#snippet breadcrumb()}
		<Breadcrumb items={[{ label: 'Profiles', href: `${base}/profiles` }, { label: 'New profile' }]} />
	{/snippet}

	<Card>
		<ProfileForm submitLabel="Create profile" onSubmit={handleSubmit} />
	</Card>
</PageContent>
