<script lang="ts">
    import type {Snippet} from 'svelte';

    interface Props {
        title: string;
        subtitle?: string;
        /** Breadcrumb rendered on the left of the panel top-bar. */
        breadcrumb?: Snippet;
        /** Action buttons rendered on the right of the panel top-bar. */
        actions?: Snippet;
        children: Snippet;
    }

    let {title, subtitle, breadcrumb, actions, children}: Props = $props();
</script>

<!-- Blue hero: grows naturally to fit title + subtitle, full main width -->
<div class="pc-hero">
    <h1 class="pc-title">{title}</h1>
    {#if subtitle}<p class="pc-subtitle">{subtitle}</p>{/if}
</div>

<!-- White elevated panel: breadcrumb + actions bar, then page content -->
<div class="pc-panel">
    {#if breadcrumb || actions}
        <div class="pc-bar">
            {#if breadcrumb}
                <div class="pc-breadcrumb">{@render breadcrumb()}</div>
            {/if}
            {#if actions}
                <div class="pc-actions">{@render actions()}</div>
            {/if}
        </div>
    {/if}

    <div class="pc-content">
        {@render children()}
    </div>
</div>

<style>
    /* =========================================================
       Hero — full width of .main, height driven by content
       ========================================================= */
    .pc-hero {
        background: var(--c-primary);
        /* Left padding aligns text with the panel content below:
           panel margin (32px) + panel padding (40px) = 72px */
        padding: 36px 72px calc(28px + 70px);
        margin-bottom: -70px; /* Pull up the hero's bottom margin so the panel overlaps it with a nice gap (28px) in between. */
    }

    .pc-title {
        font-size: 30px;
        font-weight: 700;
        color: #ffffff;
        margin: 0;
        line-height: 1.2;
    }

    .pc-subtitle {
        font-size: 19px;
        color: rgba(255, 255, 255, 0.82);
        margin: 10px 0 0;
        max-width: 520px;
        line-height: 1.5;
    }

    /* =========================================================
       Panel — inset white card with shadow below the hero
       ========================================================= */
    .pc-panel {
        background: var(--c-surface);
        box-shadow: var(--shadow-panel);
        margin: 0 32px 48px;
        padding: 15px 40px 52px;
        flex: 1;
        max-height: fit-content;
    }

    /* Top bar: breadcrumb left, action buttons right */
    .pc-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 24px 0 32px;
        gap: 16px;
    }

    .pc-breadcrumb {
        flex: 1;
    }

    .pc-actions {
        display: flex;
        gap: 10px;
        flex-shrink: 0;
        align-items: center;
    }

    .pc-bar + .pc-content {
        padding-top: 0;
    }

    /* When no bar (no breadcrumb, no actions), add breathing room */
    .pc-content:first-child {
        padding-top: 28px;
    }
</style>
