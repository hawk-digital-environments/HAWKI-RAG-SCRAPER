<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		variant: 'info' | 'warning' | 'danger' | 'success';
		icon?: string;
		children: Snippet;
	}

	const defaultIcons: Record<string, string> = {
		info: 'ℹ',
		warning: '⚠',
		danger: '✕',
		success: '✓'
	};

	let { variant, icon, children }: Props = $props();

	const displayIcon = $derived(icon ?? defaultIcons[variant]);
</script>

<div class="alert alert-{variant}">
	<span class="alert-icon">{displayIcon}</span>
	<div>{@render children()}</div>
</div>

<style>
	.alert {
		display: flex;
		gap: 12px;
		padding: 16px 18px;
		border-radius: var(--radius-lg);
		font-size: 15px;
		line-height: 1.5;
	}

	.alert-warning {
		background: var(--c-warning-light);
		border: 1px solid #fde68a;
		color: #92400e;
	}

	.alert-danger {
		background: var(--c-danger-light);
		border: 1px solid #fecaca;
		color: #991b1b;
	}

	.alert-info {
		background: var(--c-primary-light);
		border: 1px solid #bfdbfe;
		color: #1e40af;
	}

	.alert-success {
		background: var(--c-success-light);
		border: 1px solid #bbf7d0;
		color: #15803d;
	}

	.alert-icon {
		flex-shrink: 0;
		font-size: 15px;
	}
</style>
