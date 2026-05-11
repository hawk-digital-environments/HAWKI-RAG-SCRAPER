<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		label?: string;
		/** HTML `for` attribute — links label to input by id. */
		for?: string;
		required?: boolean;
		hint?: string;
		error?: string;
		/** Extra CSS classes for layout overrides (e.g. flex-1). */
		class?: string;
		children: Snippet;
	}

	let { label, for: forAttr, required = false, hint, error, class: extraClass = '', children }: Props = $props();
</script>

<div class="form-group {extraClass}">
	{#if label}
		<label class="form-label" for={forAttr}>
			{label}{#if required}<span class="required"> *</span>{/if}
		</label>
	{/if}

	{@render children()}

	{#if error}
		<p class="form-error">{error}</p>
	{:else if hint}
		<p class="form-hint">{hint}</p>
	{/if}
</div>

<style>
	.form-group {
		margin-bottom: 24px;
	}

	.form-label {
		display: block;
		font-size: 15px;
		font-weight: 500;
		color: var(--c-text);
		margin-bottom: 7px;
	}

	.required {
		color: var(--c-danger);
	}

	.form-hint {
		font-size: 14px;
		color: var(--c-text-muted);
		margin-top: 6px;
		line-height: 1.5;
	}

	.form-error {
		font-size: 14px;
		color: var(--c-danger);
		margin-top: 6px;
	}
</style>
