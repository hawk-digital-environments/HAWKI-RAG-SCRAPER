<script lang="ts">
	import { untrack } from 'svelte';
	import DynamicList from './DynamicList.svelte';
	import EntrypointList from './EntrypointList.svelte';
	import DurationInput from './DurationInput.svelte';
	import Button from '$lib/ui/Button.svelte';
	import FormGroup from '$lib/ui/FormGroup.svelte';
	import TextInput from '$lib/ui/TextInput.svelte';
	import type { Entrypoint, ProfileInput } from '$lib/api/types';

	interface Props {
		initialData?: Partial<ProfileInput>;
		submitLabel?: string;
		onSubmit: (data: ProfileInput) => void;
	}

	let { initialData = {}, submitLabel = 'Save', onSubmit }: Props = $props();
	const initial = untrack(() => initialData);

	// Basic
	let name = $state(initial.name ?? '');
	let entrypoints = $state<Entrypoint[]>(initial.entrypoints ?? []);

	// Discovery
	let discoveryHosts = $state<string[]>(initial.discovery?.hosts ?? []);

	// Forbidden
	let forbiddenHosts = $state<string[]>(initial.forbidden?.hosts ?? []);
	let forbiddenPatterns = $state<string[]>(initial.forbidden?.url_patterns ?? []);

	// Content
	let contentSelectors = $state<string[]>(initial.content?.content_selectors ?? []);
	let noisePhrases = $state<string[]>(initial.content?.noise_phrases ?? []);
	let noisePatterns = $state<string[]>(initial.content?.noise_patterns ?? []);
	let tagSelectors = $state<string[]>(initial.content?.tag_selectors ?? []);

	// Crawler configuration
	let maxConcurrency = $state(initial.max_concurrency ?? 1);
	let maxRpm = $state(initial.max_rpm ?? 60);
	let includeImages = $state(!(initial.skip_images ?? false));
	let maxImagesPerPage = $state(initial.max_images_per_page ?? 30);
	let maxPages = $state(initial.max_pages ?? 100);
	let maxLinkDensity = $state(initial.max_link_density ?? 0.4);
	let discoveryMode = $state(initial.discovery_mode ?? false);

	// Behavior
	let maxExecutionTime = $state(initial.max_execution_time ?? '24h');
	let maxStorageTime = $state(initial.max_storage_time ?? '7d');
	let rescrapeFailed = $state(initial.rescrape_failed ?? false);

	// Section visibility
	let showDiscovery = $state((initial.discovery?.hosts ?? []).length > 0);
	let showForbidden = $state(
		(initial.forbidden?.hosts ?? []).length > 0 ||
			(initial.forbidden?.url_patterns ?? []).length > 0
	);
	let showContent = $state(
		(initial.content?.content_selectors ?? []).length > 0 ||
			(initial.content?.noise_phrases ?? []).length > 0 ||
			(initial.content?.noise_patterns ?? []).length > 0 ||
			(initial.content?.tag_selectors ?? []).length > 0
	);

	let errors = $state<Record<string, string>>({});
	let submitted = $state(false);

	function validate(): boolean {
		const e: Record<string, string> = {};
		if (!name.trim()) e.name = 'Name is required.';
		if (entrypoints.length === 0) e.entrypoints = 'At least one entrypoint is required.';
		for (let i = 0; i < entrypoints.length; i++) {
			const ep = entrypoints[i];
			if (ep.type === 'host' && !ep.src.trim()) e[`ep-${i}`] = `Entrypoint ${i + 1}: hostname is required.`;
			else if (ep.type === 'sitemap' && !ep.src.trim()) e[`ep-${i}`] = `Entrypoint ${i + 1}: sitemap URL is required.`;
		}
		if (!maxExecutionTime) e.maxExecution = 'Max execution time is required.';
		if (!maxStorageTime) e.maxStorage = 'Max storage time is required.';
		if (Number(maxConcurrency) < 1) e.maxConcurrency = 'Use at least 1 parallel request.';
		if (Number(maxRpm) < 1) e.maxRpm = 'Use at least 1 request per minute.';
		if (Number(maxPages) < 0) e.maxPages = 'Use 0 or a positive number.';
		if (includeImages && (Number(maxImagesPerPage) < 0 || Number(maxImagesPerPage) > 50)) {
			e.maxImagesPerPage = 'Use a value between 0 and 50.';
		}
		if (Number(maxLinkDensity) < 0 || Number(maxLinkDensity) > 1) {
			e.maxLinkDensity = 'Use a value between 0 and 1.';
		}
		errors = e;
		return Object.keys(e).length === 0;
	}

	function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		submitted = true;
		if (!validate()) return;

		const data: ProfileInput = {
			name: name.trim(),
			entrypoints,
			discovery: discoveryHosts.filter(Boolean).length > 0 ? { hosts: discoveryHosts.filter(Boolean) } : undefined,
			forbidden:
				forbiddenHosts.filter(Boolean).length > 0 || forbiddenPatterns.filter(Boolean).length > 0
					? { hosts: forbiddenHosts.filter(Boolean), url_patterns: forbiddenPatterns.filter(Boolean) }
					: undefined,
			content:
				contentSelectors.filter(Boolean).length > 0 ||
				noisePhrases.filter(Boolean).length > 0 ||
				noisePatterns.filter(Boolean).length > 0 ||
				tagSelectors.filter(Boolean).length > 0
					? {
							content_selectors: contentSelectors.filter(Boolean),
							noise_phrases: noisePhrases.filter(Boolean),
							noise_patterns: noisePatterns.filter(Boolean),
							tag_selectors: tagSelectors.filter(Boolean)
						}
					: undefined,
			max_concurrency: Number(maxConcurrency),
			max_rpm: Number(maxRpm),
			skip_images: !includeImages,
			max_images_per_page: includeImages ? Number(maxImagesPerPage) : 0,
			max_pages: Number(maxPages),
			max_link_density: Number(maxLinkDensity),
			discovery_mode: discoveryMode,
			max_execution_time: maxExecutionTime,
			max_storage_time: maxStorageTime,
			rescrape_failed: rescrapeFailed
		};
		onSubmit(data);
	}

	$effect(() => { if (submitted) validate(); });
</script>

<form class="profile-form" onsubmit={handleSubmit} novalidate>

	<!-- ===================== BASIC ===================== -->
	<section class="form-section">
		<h3 class="section-heading">Basic</h3>

		<FormGroup label="Name" for="profile-name" required error={errors.name} hint="Human-readable identifier. Shown in all lists and task selectors.">
			<TextInput
				id="profile-name"
				bind:value={name}
				placeholder="e.g. HAWK University"
				error={!!errors.name}
			/>
		</FormGroup>
	</section>

	<!-- ===================== ENTRYPOINTS ===================== -->
	<section class="form-section">
		<h3 class="section-heading">Entrypoints <span class="required">*</span></h3>
		<p class="section-desc">
			Where the crawler starts. Add one entry per starting point — either a <strong>host</strong>
			(a domain to fully crawl) or a <strong>sitemap</strong> (a sitemap.xml URL). Both types work
			in tandem, so it often makes sense to add both a host <em>and</em> its sitemap:
		</p>
		<ol class="section-steps">
			<li>All <strong>sitemap</strong> entries are fetched first and parsed into a metadata map (<code>hostname → url → language, last_modified</code>).</li>
			<li>The actual crawl begins: each <strong>host</strong> entry is scraped via link discovery.</li>
			<li>Sitemap metadata is injected into every matching scraped page, following the <em>conflict_resolution</em> rules configured per sitemap.</li>
			<li>Any sitemap URL that was <em>not</em> reached during discovery is scraped explicitly — surfacing pages that exist in the sitemap but are unreachable from the navigation tree.</li>
		</ol>
		<p class="section-desc">
			You can add multiple entries of either type.
		</p>

		<EntrypointList {entrypoints} onchange={(v) => (entrypoints = v)} />
		{#if errors.entrypoints}<p class="form-error">{errors.entrypoints}</p>{/if}
		{#each Object.entries(errors).filter(([k]) => k.startsWith('ep-')) as [, msg]}
			<p class="form-error mt-2">{msg}</p>
		{/each}
	</section>

	<!-- ===================== DISCOVERY ===================== -->
	<section class="form-section">
		<button type="button" class="collapsible-heading" onclick={() => (showDiscovery = !showDiscovery)}>
			<span>Discovery</span>
			<span class="badge-optional">optional</span>
			<span class="chevron">{showDiscovery ? '▾' : '▸'}</span>
		</button>

		{#if showDiscovery}
			<div class="collapsible-body">
				<p class="section-desc">
					By default the crawler only follows links that stay within the entrypoint hosts. Use this
					section to allow it to also visit <strong>additional external domains</strong> — for
					example, a partner institution whose pages are linked from your main site.
				</p>
				<FormGroup hint="Add extra hosts here only if you need to follow links to external domains.">
					<p class="field-label">Additional discovery hosts</p>
					<DynamicList
						items={discoveryHosts}
						onchange={(v) => (discoveryHosts = v)}
						placeholder="external-partner.edu"
						addLabel="Add host"
					/>
				</FormGroup>
			</div>
		{/if}
	</section>

	<!-- ===================== FORBIDDEN ===================== -->
	<section class="form-section">
		<button type="button" class="collapsible-heading" onclick={() => (showForbidden = !showForbidden)}>
			<span>Forbidden</span>
			<span class="badge-optional">optional</span>
			<span class="chevron">{showForbidden ? '▾' : '▸'}</span>
		</button>

		{#if showForbidden}
			<div class="collapsible-body">
				<FormGroup hint="Hostnames to never crawl. Adding login.hawk.de also blocks *.login.hawk.de.">
					<p class="field-label">Forbidden hosts</p>
					<DynamicList
						items={forbiddenHosts}
						onchange={(v) => (forbiddenHosts = v)}
						placeholder="login.hawk.de"
						addLabel="Add host"
					/>
				</FormGroup>

				<FormGroup hint="Plain substring match (case-insensitive). Any URL containing the string is skipped.">
					<p class="field-label">Forbidden URL patterns</p>
					<DynamicList
						items={forbiddenPatterns}
						onchange={(v) => (forbiddenPatterns = v)}
						placeholder="/login"
						addLabel="Add pattern"
					/>
				</FormGroup>
			</div>
		{/if}
	</section>

	<!-- ===================== CONTENT ===================== -->
	<section class="form-section">
		<button type="button" class="collapsible-heading" onclick={() => (showContent = !showContent)}>
			<span>Content extraction</span>
			<span class="badge-optional">optional</span>
			<span class="chevron">{showContent ? '▾' : '▸'}</span>
		</button>

		{#if showContent}
			<div class="collapsible-body">
				<p class="section-desc">
					Controls how the crawler extracts and cleans page content. All fields are optional — your
					values are <strong>merged with</strong> (not replacing) the built-in defaults.
				</p>

				<FormGroup hint="Tried in order before built-in defaults (main, article, etc.).">
					<p class="field-label">Main content CSS selectors</p>
					<DynamicList items={contentSelectors} onchange={(v) => (contentSelectors = v)} placeholder=".content" addLabel="Add selector" />
				</FormGroup>

				<FormGroup hint="Case-insensitive. Blocks with 2+ matches are removed. Added on top of built-in phrases.">
					<p class="field-label">Noise phrases</p>
					<DynamicList items={noisePhrases} onchange={(v) => (noisePhrases = v)} placeholder="share this page" addLabel="Add phrase" />
				</FormGroup>

				<FormGroup hint="Matched against HTML element class/id/aria attributes. Added on top of built-in patterns.">
					<p class="field-label">Noise attribute patterns</p>
					<DynamicList items={noisePatterns} onchange={(v) => (noisePatterns = v)} placeholder="sidebar" addLabel="Add pattern" />
				</FormGroup>

				<FormGroup hint="CSS selectors for extracting article tags/keywords.">
					<p class="field-label">Tag / keyword selectors</p>
					<DynamicList items={tagSelectors} onchange={(v) => (tagSelectors = v)} placeholder="meta[name='keywords']" addLabel="Add selector" />
				</FormGroup>
			</div>
		{/if}
	</section>

	<!-- ===================== CRAWLER CONFIGURATION ===================== -->
	<section class="form-section">
		<h3 class="section-heading">Crawler configuration</h3>
		<p class="section-desc">
			These settings control how aggressively this profile runs when a task starts a crawl.
			Use conservative values for large public sites or when the target server is sensitive to load.
		</p>

		<FormGroup
			label="Max concurrency"
			for="max-concurrency"
			error={errors.maxConcurrency}
			hint="Number of page requests the crawler may run in parallel. Higher values can finish faster, but they also increase load on the target site. Start with 1 or 2 unless you know the site can handle more."
		>
			<TextInput
				id="max-concurrency"
				type="number"
				min={1}
				step={1}
				bind:value={maxConcurrency}
				error={!!errors.maxConcurrency}
			/>
		</FormGroup>

		<FormGroup
			label="Max RPM"
			for="max-rpm"
			error={errors.maxRpm}
			hint="Maximum requests per minute across this crawl. The backend default is 60, which is about one request per second. Lower this for polite crawls on sensitive sites; raise it only when the target can handle the traffic."
		>
			<TextInput
				id="max-rpm"
				type="number"
				min={1}
				step={1}
				bind:value={maxRpm}
				error={!!errors.maxRpm}
			/>
		</FormGroup>

		<FormGroup
			label="Max pages"
			for="max-pages"
			error={errors.maxPages}
			hint="Maximum number of pages to crawl. Use 0 for unlimited. Be careful with discovery mode: unlimited + discovery can crawl a very large site."
		>
			<TextInput
				id="max-pages"
				type="number"
				min={0}
				step={1}
				bind:value={maxPages}
				error={!!errors.maxPages}
			/>
		</FormGroup>

		<FormGroup
			label="Content density threshold"
			for="max-link-density"
			error={errors.maxLinkDensity}
			hint="Maximum allowed link density for extracted content. Lower values reject navigation-heavy blocks more aggressively. 0.4 is a balanced default; use values between 0 and 1."
		>
			<TextInput
				id="max-link-density"
				type="number"
				min={0}
				step={0.05}
				bind:value={maxLinkDensity}
				error={!!errors.maxLinkDensity}
			/>
		</FormGroup>

		<FormGroup>
			<label class="checkbox-label">
				<input type="checkbox" bind:checked={includeImages} />
				<span>
					<span class="label-inline">Include images</span>
					<span class="hint-block">
						When enabled, the crawler downloads images found in accepted content areas. Turn this
						off for faster text-only crawls or when image files are not needed.
					</span>
				</span>
			</label>
		</FormGroup>

		{#if includeImages}
			<FormGroup
				label="Max images per page"
				for="max-images-per-page"
				error={errors.maxImagesPerPage}
				hint="Maximum number of images to keep from each crawled page. The backend default is 30 and the allowed range is 0 to 50. Lower this for lighter output, or raise it when image-heavy pages are important."
			>
				<TextInput
					id="max-images-per-page"
					type="number"
					min={0}
					max={50}
					step={1}
					bind:value={maxImagesPerPage}
					error={!!errors.maxImagesPerPage}
				/>
			</FormGroup>
		{/if}

		<FormGroup>
			<label class="checkbox-label">
				<input type="checkbox" bind:checked={discoveryMode} />
				<span>
					<span class="label-inline">Discovery mode</span>
					<span class="hint-block">
						When enabled, the crawler follows discovered links from crawled pages. Leave it off
						when you want the crawl limited to sitemap URLs or explicitly configured entrypoints.
					</span>
				</span>
			</label>
		</FormGroup>
	</section>

	<!-- ===================== BEHAVIOR ===================== -->
	<section class="form-section">
		<h3 class="section-heading">Behavior</h3>

		<FormGroup label="Max execution time" for="max-exec" error={errors.maxExecution} hint="Job is automatically cancelled after this time. Default: 24 hours.">
			<DurationInput id="max-exec" value={maxExecutionTime} onchange={(v) => (maxExecutionTime = v)} required />
		</FormGroup>

		<FormGroup label="Max storage time" for="max-store" error={errors.maxStorage} hint="Job output is deleted this long after the job finishes. Default: 7 days.">
			<DurationInput id="max-store" value={maxStorageTime} onchange={(v) => (maxStorageTime = v)} required />
		</FormGroup>

		<FormGroup>
			<label class="checkbox-label">
				<input type="checkbox" bind:checked={rescrapeFailed} />
				<span>
					<span class="label-inline">Retry failed pages</span>
					<span class="hint-block">
						When enabled, a new job will automatically retry pages that failed in the most recent
						previous run (if that run's data still exists).
					</span>
				</span>
			</label>
		</FormGroup>
	</section>

	<div class="form-actions">
		<Button variant="primary" type="submit">{submitLabel}</Button>
	</div>
</form>

<style>
	.profile-form {
		display: flex;
		flex-direction: column;
		max-width: 700px;
	}

	.form-section {
		border-bottom: 1px solid var(--c-border);
		padding-bottom: 20px;
		margin-bottom: 20px;
	}

	.form-section:last-of-type {
		border-bottom: none;
	}

	.section-heading {
		font-size: 13px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--c-text-secondary);
		margin-bottom: 14px;
	}

	.section-desc {
		font-size: 13px;
		color: var(--c-text-secondary);
		margin-bottom: 14px;
		line-height: 1.5;
	}

	.section-steps {
		font-size: 13px;
		color: var(--c-text-secondary);
		line-height: 1.6;
		padding-left: 20px;
		margin-bottom: 12px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.collapsible-heading {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		padding: 0;
		margin-bottom: 12px;
		font-size: 13px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--c-text-secondary);
		cursor: pointer;
	}

	.collapsible-heading:hover { color: var(--c-text); }

	.collapsible-heading .chevron {
		margin-left: auto;
		font-size: 12px;
	}

	.collapsible-body { padding-top: 4px; }

	.badge-optional {
		font-size: 10px;
		font-weight: 500;
		text-transform: none;
		letter-spacing: 0;
		background: var(--c-border-subtle);
		border: 1px solid var(--c-border);
		color: var(--c-text-muted);
		padding: 1px 6px;
		border-radius: 100px;
	}

	/* Non-label field headings (inside FormGroup with no label prop) */
	.field-label {
		font-size: 13px;
		font-weight: 500;
		color: var(--c-text);
		margin-bottom: 5px;
	}

	.form-error {
		font-size: 12px;
		color: var(--c-danger);
		margin-top: 4px;
	}

	.mt-2 { margin-top: 2px; }

	.required { color: var(--c-danger); }

	.form-actions { padding-top: 8px; }

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

	code {
		font-family: var(--font-mono);
		font-size: 11px;
		background: var(--c-border-subtle);
		padding: 1px 4px;
		border-radius: 3px;
	}
</style>
