<script lang="ts">
	import { untrack } from 'svelte';
	import TextInput from '$lib/ui/TextInput.svelte';
	import SelectInput from '$lib/ui/SelectInput.svelte';
	import { parseDuration, formatDuration, DURATION_UNITS } from '$lib/utils/duration';

	interface Props {
		value: string;
		onchange: (value: string) => void;
		id?: string;
		required?: boolean;
	}

	let { value, onchange, id, required = false }: Props = $props();

	const initialParsed = untrack(() => parseDuration(value) ?? { amount: 24, unit: 'h' as const });

	let amount = $state(initialParsed.amount);
	let unit = $state(initialParsed.unit);

	$effect(() => {
		const p = parseDuration(value);
		if (p) {
			amount = p.amount;
			unit = p.unit;
		}
	});

	function handleChange() {
		if (amount > 0) {
			onchange(formatDuration({ amount, unit }));
		}
	}
</script>

<div class="duration-input">
	<TextInput
		{id}
		type="number"
		class="amount-input"
		min={1}
		step={1}
		bind:value={amount}
		{required}
		oninput={handleChange}
	/>
	<SelectInput class="unit-select" bind:value={unit} onchange={handleChange}>
		{#each DURATION_UNITS as u}
			<option value={u.value}>{u.label}</option>
		{/each}
	</SelectInput>
</div>

<style>
	.duration-input {
		display: flex;
		gap: 6px;
	}

	/* Width overrides — scoped via :global since classes live inside ui/ components */
	.duration-input :global(.amount-input) {
		width: 90px;
		flex-shrink: 0;
	}

	.duration-input :global(.unit-select) {
		flex: 1;
	}
</style>
