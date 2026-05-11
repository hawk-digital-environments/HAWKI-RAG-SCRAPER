<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		id?: string;
		value?: string;
		disabled?: boolean;
		error?: boolean;
		/** Extra CSS classes for layout overrides. */
		class?: string;
		onchange?: (e: Event) => void;
		children: Snippet;
	}

	let {
		id,
		value = $bindable(''),
		disabled = false,
		error = false,
		class: extraClass = '',
		onchange,
		children
	}: Props = $props();
</script>

<select {id} class="select {extraClass}" class:error bind:value {disabled} {onchange}>
	{@render children()}
</select>

<style>
	.select {
		padding: 10px 32px 10px 14px;
		font-size: 15px;
		font-family: var(--font-sans);
		color: var(--c-text);
		background: var(--c-surface);
		border: 1px solid var(--c-border);
		border-radius: var(--radius);
		outline: none;
		cursor: pointer;
		appearance: none;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2394a3b8' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: right 8px center;
		transition: border-color 0.1s;
		width: 100%;
	}

	.select:focus {
		border-color: var(--c-primary);
		box-shadow: 0 0 0 3px rgb(37 99 235 / 0.12);
	}

	.select.error {
		border-color: var(--c-danger);
	}

	.select:disabled {
		opacity: 0.6;
		cursor: not-allowed;
		background-color: var(--c-border-subtle);
	}
</style>
