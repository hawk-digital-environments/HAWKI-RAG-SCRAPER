<script lang="ts">
	import Button from '$lib/ui/Button.svelte';

	interface Props {
		open: boolean;
		title: string;
		message: string;
		confirmLabel?: string;
		danger?: boolean;
		onConfirm: () => void;
		onCancel: () => void;
	}

	let {
		open,
		title,
		message,
		confirmLabel = 'Confirm',
		danger = false,
		onConfirm,
		onCancel
	}: Props = $props();
</script>

{#if open}
	<div class="overlay" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
		<div class="dialog">
			<h2 class="dialog-title" id="dialog-title">{title}</h2>
			<p class="dialog-message">{message}</p>
			<div class="dialog-actions">
				<Button variant="secondary" onclick={onCancel}>Cancel</Button>
				<Button variant={danger ? 'danger' : 'primary'} onclick={onConfirm}>
					{confirmLabel}
				</Button>
			</div>
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgb(0 0 0 / 0.4);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}

	.dialog {
		background: var(--c-surface);
		border-radius: var(--radius-lg);
		box-shadow: var(--shadow-md);
		padding: 24px;
		width: 100%;
		max-width: 420px;
		margin: 16px;
	}

	.dialog-title {
		font-size: 16px;
		font-weight: 600;
		margin-bottom: 10px;
	}

	.dialog-message {
		font-size: 13px;
		color: var(--c-text-secondary);
		line-height: 1.6;
		margin-bottom: 20px;
	}

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
</style>
