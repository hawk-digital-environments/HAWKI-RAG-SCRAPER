<script lang="ts">
	interface Props {
		/**
		 * Controls colour via CSS custom properties.
		 * Built-in statuses: running | paused | stopping | completed | failed | cancelled | manual | scheduled
		 * Any custom string falls back gracefully.
		 */
		status: string;
		/** Override the displayed label. Defaults to capitalised status. */
		label?: string;
	}

	let { status, label }: Props = $props();

	const display = $derived(label ?? status.charAt(0).toUpperCase() + status.slice(1));
</script>

<span class="badge badge-{status}">{display}</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		border-radius: 100px;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.02em;
		white-space: nowrap;
	}

	.badge-running {
		background: var(--c-badge-running-bg);
		color: var(--c-badge-running-text);
	}
	.badge-paused {
		background: var(--c-badge-paused-bg);
		color: var(--c-badge-paused-text);
	}
	.badge-stopping {
		background: var(--c-badge-stopping-bg);
		color: var(--c-badge-stopping-text);
	}
	.badge-completed {
		background: var(--c-badge-completed-bg);
		color: var(--c-badge-completed-text);
	}
	.badge-failed {
		background: var(--c-badge-failed-bg);
		color: var(--c-badge-failed-text);
	}
	.badge-cancelled {
		background: var(--c-badge-cancelled-bg);
		color: var(--c-badge-cancelled-text);
	}
	.badge-manual {
		background: var(--c-badge-manual-bg);
		color: var(--c-badge-manual-text);
	}
	.badge-scheduled {
		background: var(--c-badge-scheduled-bg);
		color: var(--c-badge-scheduled-text);
	}
</style>
