<script lang="ts">
	interface Props {
		id?: string;
		type?: 'text' | 'email' | 'url' | 'password' | 'number' | 'search';
		value?: string | number;
		placeholder?: string;
		disabled?: boolean;
		readonly?: boolean;
		error?: boolean;
		/** Extra CSS classes for layout overrides (e.g. width constraints). */
	class?: string;
	min?: string | number;
	max?: string | number;
	step?: string | number;
		required?: boolean;
		oninput?: (e: Event) => void;
		onchange?: (e: Event) => void;
	}

	let {
		id,
		type = 'text',
		value = $bindable<string | number>(''),
		placeholder,
		disabled = false,
		readonly = false,
		error = false,
		class: extraClass = '',
		min,
		max,
		step,
		required = false,
		oninput,
		onchange
	}: Props = $props();
</script>

<input
	{id}
	{type}
	class="input {extraClass}"
	class:error
	bind:value
	{placeholder}
	{disabled}
	{readonly}
	{min}
	{max}
	{step}
	{required}
	{oninput}
	{onchange}
/>

<style>
	.input {
		width: 100%;
		padding: 10px 14px;
		font-size: 15px;
		font-family: var(--font-sans);
		color: var(--c-text);
		background: var(--c-surface);
		border: 1px solid var(--c-border);
		border-radius: var(--radius);
		outline: none;
		transition: border-color 0.1s, box-shadow 0.1s;
	}

	.input:focus {
		border-color: var(--c-primary);
		box-shadow: 0 0 0 3px rgb(37 99 235 / 0.12);
	}

	.input.error {
		border-color: var(--c-danger);
	}

	.input.error:focus {
		box-shadow: 0 0 0 3px rgb(239 68 68 / 0.12);
	}

	.input:disabled {
		opacity: 0.6;
		cursor: not-allowed;
		background: var(--c-border-subtle);
	}
</style>
