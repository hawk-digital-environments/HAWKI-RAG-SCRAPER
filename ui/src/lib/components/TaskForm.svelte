<script lang="ts">
	import { isValidCron } from 'cron-validator';
	import type { Profile, TaskInput } from '$lib/api/types';
	import Button from '$lib/ui/Button.svelte';
	import Alert from '$lib/ui/Alert.svelte';
	import FormGroup from '$lib/ui/FormGroup.svelte';
	import TextInput from '$lib/ui/TextInput.svelte';
	import SelectInput from '$lib/ui/SelectInput.svelte';
	import { base } from '$app/paths';
	import cronstrue from 'cronstrue';

	interface Props {
		profiles: Profile[];
		initialData?: Partial<TaskInput>;
		submitLabel?: string;
		onSubmit: (data: TaskInput) => void;
	}

	let {
		profiles,
		initialData = {},
		submitLabel = 'Save',
		onSubmit
	}: Props = $props();

	let name = $state(initialData.name ?? '');
	let profileId = $state(initialData.profileId ?? (profiles[0]?.id ?? ''));
	let scheduleEnabled = $state(!!initialData.schedule);
	let schedule = $state(initialData.schedule ?? '');

	let submitted = $state(false);

	// Real-time cron validation
	const cronError = $derived(
		scheduleEnabled && schedule.trim() && !isValidCron(schedule.trim())
			? 'Invalid cron expression.'
			: ''
	);
	const cronMissing = $derived(
		scheduleEnabled && submitted && !schedule.trim()
			? 'Cron expression is required when scheduling is enabled.'
			: ''
	);

	let errors = $state<Record<string, string>>({});

	function validate(): boolean {
		const e: Record<string, string> = {};
		if (!name.trim()) e.name = 'Name is required.';
		if (!profileId) e.profileId = 'Please select a profile.';
		if (scheduleEnabled) {
			if (!schedule.trim()) e.schedule = 'Cron expression is required when scheduling is enabled.';
			else if (cronError) e.schedule = cronError;
		}
		errors = e;
		return Object.keys(e).length === 0;
	}

	function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		submitted = true;
		if (!validate()) return;
		onSubmit({ name: name.trim(), profileId, schedule: scheduleEnabled ? schedule.trim() : undefined });
	}

	$effect(() => { if (submitted) validate(); });

	const cronHuman = $derived.by(() => {
		if (!schedule.trim() || cronError) return '';
		try {
			return cronstrue.toString(schedule.trim());
		} catch {
			return '';
		}
	});
</script>

<form class="task-form" onsubmit={handleSubmit} novalidate>
	<!-- Name -->
	<FormGroup label="Task name" for="task-name" required hint="A short, human-readable label for this task." error={errors.name}>
		<TextInput id="task-name" bind:value={name} placeholder="e.g. HAWK Weekly Crawl" error={!!errors.name} />
	</FormGroup>

	<!-- Profile -->
	<FormGroup label="Profile" for="task-profile" required error={errors.profileId}>
		<div class="profile-row">
			<SelectInput id="task-profile" bind:value={profileId} error={!!errors.profileId}>
				{#if profiles.length === 0}
					<option value="">No profiles available</option>
				{/if}
				{#each profiles as p}
					<option value={p.id}>{p.name}</option>
				{/each}
			</SelectInput>
			<Button variant="secondary" size="sm" href="{base}/profiles/new" title="Create a new profile">+ New Profile</Button>
		</div>
		{#if profiles.length === 0 && !errors.profileId}
			<p class="hint">No profiles exist yet. Create one using the button above.</p>
		{/if}
	</FormGroup>

	<!-- Schedule toggle -->
	<FormGroup>
		<label class="checkbox-label">
			<input type="checkbox" bind:checked={scheduleEnabled} />
			<span>
				<span class="label-inline">Enable schedule</span>
				<span class="hint-block">
					If disabled, this task is manual and must be started explicitly.
				</span>
			</span>
		</label>
	</FormGroup>

	<!-- Cron expression -->
	{#if scheduleEnabled}
		<FormGroup
			label="Cron expression"
			for="task-schedule"
			required
			error={cronMissing || cronError}
			hint="Standard 5-field cron syntax, e.g. 0 2 * * 1"
		>
			<TextInput
				id="task-schedule"
				bind:value={schedule}
				placeholder="0 2 * * 1"
				error={!!(cronError || cronMissing)}
			/>
			{#if cronHuman}
				<p class="cron-human">{cronHuman}</p>
			{/if}
		</FormGroup>
	{/if}

	<!-- Profile info callout -->
	{#if profileId}
		{@const profile = profiles.find((p) => p.id === profileId)}
		{#if profile}
			<Alert variant="info">
				Max execution time and storage retention are configured in the selected profile
				(<strong>{profile.name}</strong>): execution cancels after
				<strong>{profile.max_execution_time}</strong>, output retained for
				<strong>{profile.max_storage_time}</strong>.
			</Alert>
		{/if}
	{/if}

	<div class="form-actions">
		<Button variant="primary" type="submit">{submitLabel}</Button>
	</div>
</form>

<style>
	.task-form {
		display: flex;
		flex-direction: column;
		gap: 4px;
		max-width: 540px;
	}

	.profile-row {
		display: flex;
		gap: 8px;
		align-items: center;
	}

	.profile-row :global(.select) {
		flex: 1;
	}

	.hint {
		font-size: 12px;
		color: var(--c-text-muted);
		margin-top: 4px;
		line-height: 1.5;
	}

	.cron-human {
		font-size: 12px;
		color: var(--c-success, #16a34a);
		margin-top: 4px;
		line-height: 1.5;
	}

	.label-inline {
		font-size: 13px;
		font-weight: 500;
		color: var(--c-text);
	}

	.hint-block {
		display: block;
		font-size: 12px;
		color: var(--c-text-muted);
		margin-top: 2px;
	}

	.checkbox-label {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		cursor: pointer;
	}

	.checkbox-label input[type='checkbox'] {
		margin-top: 2px;
		flex-shrink: 0;
		width: 15px;
		height: 15px;
		accent-color: var(--c-primary);
		cursor: pointer;
	}

	.form-actions {
		margin-top: 8px;
		padding-top: 16px;
		border-top: 1px solid var(--c-border);
	}
</style>
