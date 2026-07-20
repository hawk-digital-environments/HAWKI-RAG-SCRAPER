<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
		size?: 'default' | 'sm' | 'icon';
		href?: string;
		disabled?: boolean;
		type?: 'button' | 'submit' | 'reset';
		title?: string;
		onclick?: (e: MouseEvent) => void;
		children: Snippet;
	}

	let {
		variant = 'secondary',
		size = 'default',
		href,
		disabled = false,
		type = 'button',
		title,
		onclick,
		children
	}: Props = $props();

	const cls = $derived(
		['btn', `btn-${variant}`, size !== 'default' ? `btn-${size}` : ''].filter(Boolean).join(' ')
	);
</script>

{#if href}
	<a {href} class={cls} {title}>{@render children()}</a>
{:else}
	<button class={cls} {type} {disabled} {title} {onclick}>{@render children()}</button>
{/if}

<style>
	.btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 9px 18px;
		font-size: 15px;
		font-weight: 500;
		font-family: var(--font-sans);
		border-radius: var(--radius);
		border: 1px solid transparent;
		cursor: pointer;
		text-decoration: none;
		transition: background 0.1s, border-color 0.1s, color 0.1s, opacity 0.1s;
		white-space: nowrap;
		line-height: 1.4;
	}

	.btn:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.btn-primary {
		background: var(--c-primary);
		color: var(--c-primary-fg);
		border-color: var(--c-primary);
	}
	.btn-primary:hover:not(:disabled) {
		background: var(--c-primary-hover);
		border-color: var(--c-primary-hover);
		text-decoration: none;
	}

	.btn-secondary {
		background: var(--c-surface);
		color: var(--c-text);
		border-color: var(--c-border);
	}
	.btn-secondary:hover:not(:disabled) {
		background: var(--c-bg);
		text-decoration: none;
	}

	.btn-danger {
		background: var(--c-danger);
		color: var(--c-danger-fg);
		border-color: var(--c-danger);
	}
	.btn-danger:hover:not(:disabled) {
		background: var(--c-danger-hover);
		border-color: var(--c-danger-hover);
		text-decoration: none;
	}

	.btn-ghost {
		background: transparent;
		color: var(--c-text-secondary);
		border-color: transparent;
	}
	.btn-ghost:hover:not(:disabled) {
		background: var(--c-bg);
		color: var(--c-text);
		text-decoration: none;
	}

	.btn-sm {
		padding: 6px 12px;
		font-size: 14px;
	}

	.btn-icon {
		padding: 6px;
		font-size: 14px;
	}
</style>
