<svelte:options runes={false} />

<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	type ProfileEntry = {
		name: string;
		hostPath: string;
		containerPath: string;
		match_hosts: string[];
		profile: Record<string, unknown>;
		readonlyExample?: boolean;
	};

	type QueueEntry = {
		name: string;
		vhost: string;
		state: string;
		messages: number;
		messages_ready: number;
		messages_unacknowledged: number;
		consumers: number;
	};

	type JobStatus = {
		job_id: string;
		status: string;
		message: string;
		pages_crawled: number;
		total_pages: number;
		started_at?: string;
		completed_at?: string;
		output_directory?: string;
	};

	type SummaryCounts = {
		found: number;
		completed: number;
		missed: number;
	};

	const hiddenQueueNames = new Set(['crawl_jobs', 'crawl_jobs_retry', 'failed_jobs']);

	type CrawlForm = {
		job_id: string;
		url: string;
		output_dir: string;
		label: string;
		site_profile_path: string;
		rescrape_failed: boolean;
		sitemap: boolean;
		sitemap_base: string;
		sitemap_output: string;
		sitemap_only: boolean;
		discovery_mode: boolean;
		skip_images: boolean;
		max_pages: number;
		max_concurrency: number;
		max_rpm: number;
		max_images_per_page: number;
		request_delay: string;
		image_exceptions: string;
		date_selector: string;
		sitemap_start_page: string;
		sitemap_pages: string;
		min_word_count: number;
		max_link_density: number;
		max_link_density_words: number;
		wait_until: string;
		page_timeout_ms: number;
	};

	const defaults: CrawlForm = {
		job_id: 'Site_Sample',
		url: 'https://www.hawk.de',
		output_dir: 'output',
		label: '',
		site_profile_path: '/app/profiles/hawk.json',
		rescrape_failed: false,
		sitemap: true,
		sitemap_base: 'https://www.hawk.de/sitemaps/main/sitemap.xml',
		sitemap_output: '/app/shared/sitemaps/site_sitemap.json',
		sitemap_only: false,
		discovery_mode: false,
		skip_images: false,
		max_pages: 100,
		max_concurrency: 1,
		max_rpm: 20,
		max_images_per_page: 30,
		request_delay: '',
		image_exceptions: '',
		date_selector: '',
		sitemap_start_page: '1',
		sitemap_pages: '6',
		min_word_count: 20,
		max_link_density: 0.4,
		max_link_density_words: 200,
		wait_until: 'domcontentloaded',
		page_timeout_ms: 90000
	};

	let form: CrawlForm = { ...defaults };
	let submitState = '';
	let submitError = '';
	let submitResult: Record<string, unknown> | null = null;

	let profiles: ProfileEntry[] = [];
	let selectedProfileName = '';
	let profileEditorText = '{\n  "name": "example_university"\n}';
	let newProfileName = '';
	let profileError = '';
	let profileInfo = '';

	let queues: QueueEntry[] = [];
	let queueError = '';

	let jobs: JobStatus[] = [];
	let jobsError = '';
	let stopStateByJob: Record<string, string> = {};
	let selectedJobId = '';
	let summaryCountsByJob: Record<string, SummaryCounts> = {};
	let autoRefresh = true;
	let refreshHandle: ReturnType<typeof setInterval> | null = null;

	function newGeneratedJobId(prefix = 'crawl') {
		return `${prefix}_${Date.now()}`;
	}

	function applyPreset(preset: 'sample' | 'full' | 'sitemap-only' | 'json-sitemap') {
		if (preset === 'sample') {
			form = {
				...form,
				job_id: 'Site_Sample',
				url: 'https://www.hawk.de',
				max_pages: 100,
				discovery_mode: false,
				sitemap_only: false,
				max_concurrency: 1,
				max_rpm: 20,
				skip_images: false
			};
			return;
		}
		if (preset === 'full') {
			form = {
				...form,
				job_id: 'Site_Full',
				url: 'https://www.hawk.de',
				max_pages: 40000,
				discovery_mode: false,
				sitemap_only: false,
				max_concurrency: 2,
				max_rpm: 40,
				skip_images: false
			};
			return;
		}
		if (preset === 'sitemap-only') {
			form = {
				...form,
				job_id: 'Site_Full',
				url: form.sitemap_base,
				sitemap_only: true,
				discovery_mode: false,
				max_pages: 0,
				max_concurrency: 2,
				max_rpm: 40
			};
			return;
		}
		form = {
			...form,
			job_id: 'JsonSitemap_Job',
			url: 'https://projekte.g.hawk.de/sitemap.json',
			sitemap: false,
			sitemap_only: false,
			discovery_mode: false,
			max_pages: 6000,
			max_concurrency: 2,
			max_rpm: 40,
			skip_images: false
		};
	}

	function buildPayload() {
		const payload: Record<string, unknown> = {
			job_id: form.job_id.trim(),
			url: form.url.trim(),
			output_dir: form.output_dir.trim(),
			label: form.label.trim() || undefined,
			site_profile_path: form.site_profile_path.trim() || undefined,
			rescrape_failed: form.rescrape_failed,
			sitemap: form.sitemap,
			sitemap_base: form.sitemap_base.trim() || undefined,
			sitemap_output: form.sitemap_output.trim() || undefined,
			sitemap_only: form.sitemap_only,
			discovery_mode: form.discovery_mode,
			skip_images: form.skip_images,
			max_pages: form.max_pages,
			max_concurrency: form.max_concurrency,
			max_rpm: form.max_rpm,
			max_images_per_page: form.max_images_per_page,
			image_exceptions: form.image_exceptions.trim() || undefined,
			date_selector: form.date_selector.trim() || undefined,
			min_word_count: form.min_word_count,
			max_link_density: form.max_link_density,
			max_link_density_words: form.max_link_density_words,
			wait_until: form.wait_until.trim() || 'domcontentloaded',
			page_timeout_ms: form.page_timeout_ms
		};

		if (form.request_delay.trim()) {
			payload.request_delay = Number(form.request_delay);
		}
		if (form.sitemap_start_page.trim()) {
			payload.sitemap_start_page = Number(form.sitemap_start_page);
		}
		if (form.sitemap_pages.trim()) {
			payload.sitemap_pages = Number(form.sitemap_pages);
		}

		return payload;
	}

	async function submitJob() {
		submitState = 'Submitting job...';
		submitError = '';
		submitResult = null;
		try {
			const payload = buildPayload();
			const response = await fetch('/api/crawler/submit', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify(payload)
			});
			const data = await response.json();
			if (!response.ok) {
				const baseError = typeof data?.error === 'string' ? data.error : JSON.stringify(data);
				const hint = typeof data?.hint === 'string' ? ` (${data.hint})` : '';
				submitError = `${baseError}${hint}`;
				submitState = '';
				return;
			}
			submitResult = data;
			submitState = 'Submitted.';
			await refreshJobs();
			await refreshQueues();
		} catch (error) {
			submitError = `Submission failed: ${error}`;
			submitState = '';
		}
	}

	async function loadProfiles() {
		profileError = '';
		try {
			const response = await fetch('/api/profiles');
			const payload = await response.json();
			if (!response.ok) {
				profileError = payload?.error ?? 'Failed to load profiles';
				return;
			}
			profiles = Array.isArray(payload?.profiles) ? payload.profiles : [];
		} catch (error) {
			profileError = `Failed to load profiles: ${error}`;
			return;
		}

		if (!profiles.length) {
			profileEditorText = '{\n  "name": "example_university"\n}';
			selectedProfileName = '';
			return;
		}

		const selectedExists = profiles.some((entry) => entry.name === selectedProfileName);
		if (!selectedExists) {
			selectedProfileName = profiles[0].name;
		}
		await selectProfile(selectedProfileName);
	}

	async function selectProfile(name: string) {
		selectedProfileName = name;
		profileError = '';
		profileInfo = '';
		try {
			const response = await fetch(`/api/profiles/${encodeURIComponent(name)}`);
			const payload = await response.json();
			if (!response.ok) {
				profileError = payload?.error ?? 'Failed to load profile';
				return;
			}
			profileEditorText = JSON.stringify(payload.profile ?? {}, null, 2);
		} catch (error) {
			profileError = `Failed to load profile: ${error}`;
		}
	}

	async function saveProfile() {
		profileError = '';
		profileInfo = '';

		let parsed: Record<string, unknown>;
		try {
			const value = JSON.parse(profileEditorText);
			if (!value || typeof value !== 'object' || Array.isArray(value)) {
				profileError = 'Profile JSON must be an object.';
				return;
			}
			parsed = value as Record<string, unknown>;
		} catch (error) {
			profileError = `Invalid JSON: ${error}`;
			return;
		}

		const inferredName = typeof parsed.name === 'string' ? parsed.name.trim() : '';
		const name = (newProfileName.trim() || selectedProfileName.trim() || inferredName).replace(
			/\.json$/i,
			''
		);
		if (!name) {
			profileError = 'Choose an existing profile, enter a new profile name, or set profile.name.';
			return;
		}
		try {
			const response = await fetch('/api/profiles', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ name, profile: parsed })
			});
			const payload = await response.json();
			if (!response.ok) {
				profileError = payload?.error ?? 'Profile save failed';
				return;
			}

			selectedProfileName = payload.name;
			newProfileName = '';
			profileInfo = `Saved ${payload.name}.json (${payload.hostPath})`;
			await loadProfiles();
		} catch (error) {
			profileError = `Profile save failed: ${error}`;
		}
	}

	function applySelectedProfileToJob() {
		const profile = profiles.find((entry) => entry.name === selectedProfileName);
		if (!profile) {
			profileError = 'Select a profile first.';
			return;
		}
		form.site_profile_path = profile.containerPath;
	}

	async function refreshQueues() {
		queueError = '';
		try {
			const response = await fetch('/api/rabbitmq/queues');
			const payload = await response.json();
			if (!response.ok) {
				queueError = payload?.error ?? 'Queue request failed';
				queues = [];
				return;
			}
			queues = Array.isArray(payload?.queues)
				? payload.queues.filter((queue: QueueEntry) => !hiddenQueueNames.has(queue.name))
				: [];
		} catch (error) {
			queueError = `Queue request failed: ${error}`;
		}
	}

	function deriveFallbackCounts(job: JobStatus): SummaryCounts {
		const found = Number.isFinite(job.total_pages) ? job.total_pages : 0;
		const completed = Number.isFinite(job.pages_crawled) ? job.pages_crawled : 0;
		const missed = Math.max(found - completed, 0);
		return { found, completed, missed };
	}

	function countsForJob(job: JobStatus): SummaryCounts {
		return summaryCountsByJob[job.job_id] ?? deriveFallbackCounts(job);
	}

	async function loadSummaryForJob(jobId: string) {
		selectedJobId = jobId;
		try {
			const response = await fetch(`/api/crawler/job/${encodeURIComponent(jobId)}/summary`);
			const payload = await response.json();
			if (response.ok && payload?.found && payload?.counts) {
				summaryCountsByJob = {
					...summaryCountsByJob,
					[jobId]: payload.counts as SummaryCounts
				};
			}
		} catch {
			// Keep fallback counters.
		}
	}

	async function refreshJobs() {
		jobsError = '';
		try {
			const response = await fetch('/api/crawler/jobs');
			const payload = await response.json();
			if (!response.ok) {
				const baseError = payload?.error ?? 'Failed to load jobs';
				const hint = typeof payload?.hint === 'string' ? ` (${payload.hint})` : '';
				jobsError = `${baseError}${hint}`;
				jobs = [];
				return;
			}
			const map = payload?.jobs ?? {};
			jobs = Object.values(map)
				.filter((item): item is JobStatus => !!item && typeof item === 'object' && 'job_id' in item)
				.sort((a, b) => (new Date(b.started_at ?? 0).getTime() || 0) - (new Date(a.started_at ?? 0).getTime() || 0));

			for (const job of jobs.slice(0, 25)) {
				if (!summaryCountsByJob[job.job_id]) {
					void loadSummaryForJob(job.job_id);
				}
			}
		} catch (error) {
			jobsError = `Failed to load jobs: ${error}`;
		}
	}

	function canStopJob(job: JobStatus) {
		return !['completed', 'failed', 'cancelled'].includes(job.status);
	}

	async function stopJob(jobId: string) {
		stopStateByJob = { ...stopStateByJob, [jobId]: 'Stopping...' };
		try {
			const response = await fetch(`/api/crawler/job/${encodeURIComponent(jobId)}/cancel`, {
				method: 'POST'
			});
			const payload = await response.json();
			if (!response.ok) {
				const detail = payload?.detail ?? payload?.error ?? 'Stop request failed';
				stopStateByJob = { ...stopStateByJob, [jobId]: String(detail) };
				return;
			}
			stopStateByJob = { ...stopStateByJob, [jobId]: payload?.message ?? 'Stop requested' };
			await refreshJobs();
		} catch (error) {
			stopStateByJob = { ...stopStateByJob, [jobId]: `Stop failed: ${error}` };
		}
	}

	function startAutoRefresh() {
		if (typeof window === 'undefined') {
			return;
		}
		if (refreshHandle) {
			clearInterval(refreshHandle);
			refreshHandle = null;
		}
		if (!autoRefresh) {
			return;
		}
		refreshHandle = setInterval(() => {
			void refreshJobs();
			void refreshQueues();
		}, 8000);
	}

	onMount(async () => {
		await Promise.all([loadProfiles(), refreshQueues(), refreshJobs()]);
		startAutoRefresh();
	});

	onDestroy(() => {
		if (refreshHandle) {
			clearInterval(refreshHandle);
		}
	});

	$: autoRefresh, startAutoRefresh();
</script>

<svelte:head>
	<title>Crawler Job Control</title>
</svelte:head>

<div class="page">
	<header class="hero">
		<h1>Crawler Job Control Room</h1>
		<p>Submit crawl jobs with full Makefile-level parameters, manage university profiles, and monitor RabbitMQ queues and job outcomes.</p>
	</header>

	<section class="panel profiles">
		<div class="panel-head">
			<h2>University Profiles</h2>
			<div class="row">
				<button on:click={loadProfiles}>Refresh Profiles</button>
				<button class="secondary" on:click={applySelectedProfileToJob}>Use In Job Form</button>
			</div>
		</div>
		<div class="grid two-col">
			<div>
				<p class="field-label">Saved Profiles</p>
				<div class="profile-list">
					{#if profiles.length === 0}
						<p class="muted">No profiles found. Create one below.</p>
					{:else}
						{#each profiles as profile}
							<button
								type="button"
								class:selected={selectedProfileName === profile.name}
								on:click={() => selectProfile(profile.name)}
							>
								{profile.name}.json{profile.readonlyExample ? ' (example)' : ''}
							</button>
						{/each}
					{/if}
				</div>
				<label for="new-profile-name">New Profile Name</label>
				<input id="new-profile-name" placeholder="e.g. tu-berlin" bind:value={newProfileName} />
				<p class="muted">Reads/writes actual files in `profiles/*.json` (or `.json.example` as read-only templates).</p>
			</div>
			<div>
				<label for="profile-json-editor">Profile JSON Editor</label>
				<textarea id="profile-json-editor" rows="13" bind:value={profileEditorText}></textarea>
				<div class="row">
					<button on:click={saveProfile}>Save Profile</button>
				</div>
				{#if profileInfo}
					<p class="ok">{profileInfo}</p>
				{/if}
				{#if profileError}
					<p class="error">{profileError}</p>
				{/if}
			</div>
		</div>
	</section>

	<section class="panel">
		<div class="panel-head">
			<h2>Submit Scrape Job</h2>
			<div class="row">
				<button class="secondary" on:click={() => (form = { ...defaults, job_id: newGeneratedJobId('crawl') })}>Reset Defaults</button>
				<button class="secondary" on:click={() => (form.job_id = newGeneratedJobId('crawl'))}>New Job ID</button>
			</div>
		</div>
		<div class="preset-row">
			<button class="chip" on:click={() => applyPreset('sample')}>Make Preset: `crawl-sample`</button>
			<button class="chip" on:click={() => applyPreset('full')}>Make Preset: `crawl-site/full`</button>
			<button class="chip" on:click={() => applyPreset('sitemap-only')}>Make Preset: `crawl-site-sitemap-only`</button>
			<button class="chip" on:click={() => applyPreset('json-sitemap')}>Make Preset: `crawl-json-sitemap`</button>
		</div>

		<div class="grid three-col">
			<div class="field"><label for="job_id">job_id</label><input id="job_id" bind:value={form.job_id} /></div>
			<div class="field"><label for="url">url</label><input id="url" bind:value={form.url} /></div>
			<div class="field"><label for="site_profile_path">site_profile_path</label><input id="site_profile_path" bind:value={form.site_profile_path} /></div>
			<div class="field"><label for="output_dir">output_dir</label><input id="output_dir" bind:value={form.output_dir} /></div>
			<div class="field"><label for="label">label</label><input id="label" bind:value={form.label} /></div>
			<div class="field"><label for="sitemap_base">sitemap_base</label><input id="sitemap_base" bind:value={form.sitemap_base} /></div>
			<div class="field"><label for="sitemap_output">sitemap_output</label><input id="sitemap_output" bind:value={form.sitemap_output} /></div>
			<div class="field"><label for="date_selector">date_selector</label><input id="date_selector" bind:value={form.date_selector} /></div>
			<div class="field"><label for="image_exceptions">image_exceptions</label><input id="image_exceptions" bind:value={form.image_exceptions} /></div>
			<div class="field"><label for="max_pages">max_pages</label><input id="max_pages" type="number" bind:value={form.max_pages} /></div>
			<div class="field"><label for="max_concurrency">max_concurrency</label><input id="max_concurrency" type="number" bind:value={form.max_concurrency} min="1" max="20" /></div>
			<div class="field"><label for="max_rpm">max_rpm</label><input id="max_rpm" type="number" bind:value={form.max_rpm} min="1" /></div>
			<div class="field"><label for="max_images_per_page">max_images_per_page</label><input id="max_images_per_page" type="number" bind:value={form.max_images_per_page} min="0" max="50" /></div>
			<div class="field"><label for="request_delay">request_delay (ms)</label><input id="request_delay" type="number" bind:value={form.request_delay} placeholder="optional" /></div>
			<div class="field"><label for="sitemap_start_page">sitemap_start_page</label><input id="sitemap_start_page" type="number" bind:value={form.sitemap_start_page} /></div>
			<div class="field"><label for="sitemap_pages">sitemap_pages</label><input id="sitemap_pages" type="number" bind:value={form.sitemap_pages} /></div>
			<div class="field"><label for="min_word_count">min_word_count</label><input id="min_word_count" type="number" bind:value={form.min_word_count} min="0" /></div>
			<div class="field">
				<label for="max_link_density">max_link_density</label>
				<input id="max_link_density" type="number" step="0.01" bind:value={form.max_link_density} min="0" max="1" />
				<p class="hint">0.4 allows content where up to ~40% is link text. Raise to 0.6/0.8 if useful pages are missing; lower to 0.2/0.3 if too many navigation/list pages appear.</p>
			</div>
			<div class="field"><label for="max_link_density_words">max_link_density_words</label><input id="max_link_density_words" type="number" bind:value={form.max_link_density_words} min="0" /></div>
			<div class="field"><label for="wait_until">wait_until</label><input id="wait_until" bind:value={form.wait_until} /></div>
			<div class="field"><label for="page_timeout_ms">page_timeout_ms</label><input id="page_timeout_ms" type="number" bind:value={form.page_timeout_ms} min="1" /></div>
		</div>

		<div class="toggle-grid">
			<label><input type="checkbox" bind:checked={form.sitemap} /> sitemap</label>
			<label><input type="checkbox" bind:checked={form.sitemap_only} /> sitemap_only</label>
			<label><input type="checkbox" bind:checked={form.discovery_mode} /> discovery_mode</label>
			<label><input type="checkbox" bind:checked={form.skip_images} /> skip_images</label>
			<label><input type="checkbox" bind:checked={form.rescrape_failed} /> rescrape_failed</label>
		</div>

		<div class="row">
			<button class="submit" on:click={submitJob}>Submit Crawl Job</button>
			<span class="muted">{submitState}</span>
		</div>
		{#if submitError}
			<p class="error">{submitError}</p>
		{/if}
		{#if submitResult}
			<pre>{JSON.stringify(submitResult, null, 2)}</pre>
		{/if}
	</section>

	<section class="panel">
		<div class="panel-head">
			<h2>RabbitMQ Queue + Job Monitor</h2>
			<div class="row">
				<label class="inline"><input type="checkbox" bind:checked={autoRefresh} /> Auto refresh</label>
				<button on:click={refreshQueues}>Refresh Queues</button>
				<button on:click={refreshJobs}>Refresh Jobs</button>
			</div>
		</div>

		<div class="grid two-col">
			<div>
				<h3>Queues</h3>
				{#if queueError}<p class="error">{queueError}</p>{/if}
				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Queue</th>
								<th>Ready</th>
								<th>Unacked</th>
								<th>Total</th>
								<th>Consumers</th>
							</tr>
						</thead>
						<tbody>
							{#each queues as queue}
								<tr>
									<td>{queue.name}</td>
									<td>{queue.messages_ready}</td>
									<td>{queue.messages_unacknowledged}</td>
									<td>{queue.messages}</td>
									<td>{queue.consumers}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>

			<div>
				<h3>Jobs</h3>
				{#if jobsError}<p class="error">{jobsError}</p>{/if}
				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Job ID</th>
								<th>Status</th>
								<th>URLs Found</th>
								<th>URLs Completed</th>
								<th>URLs Missed</th>
								<th>Action</th>
							</tr>
						</thead>
						<tbody>
							{#each jobs as job}
								<tr class:selected={selectedJobId === job.job_id} on:click={() => loadSummaryForJob(job.job_id)}>
									<td>{job.job_id}</td>
									<td><span class={`status ${job.status}`}>{job.status}</span></td>
									<td>{countsForJob(job).found}</td>
									<td>{countsForJob(job).completed}</td>
									<td>{countsForJob(job).missed}</td>
									<td>
										<button
											class="danger"
											disabled={!canStopJob(job)}
											on:click|stopPropagation={() => stopJob(job.job_id)}
										>
											Stop
										</button>
										{#if stopStateByJob[job.job_id]}
											<span class="action-state">{stopStateByJob[job.job_id]}</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</section>
</div>

<style>
	@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=IBM+Plex+Mono:wght@400;600&display=swap');

	:global(body) {
		margin: 0;
		font-family: 'Space Grotesk', 'Avenir Next', 'Helvetica Neue', sans-serif;
		background:
			radial-gradient(circle at 15% 20%, rgba(0, 214, 255, 0.2), transparent 42%),
			radial-gradient(circle at 85% 12%, rgba(72, 132, 255, 0.25), transparent 38%),
			linear-gradient(160deg, #081322 0%, #0d1d34 55%, #08101f 100%);
		color: #eaf6ff;
	}

	.page {
		max-width: 1280px;
		margin: 0 auto;
		padding: 1.1rem;
		display: grid;
		gap: 1rem;
	}

	.hero {
		padding: 1.2rem;
		border: 1px solid rgba(110, 200, 255, 0.4);
		background: linear-gradient(140deg, rgba(8, 28, 54, 0.9), rgba(12, 44, 79, 0.92));
		border-radius: 1rem;
		animation: fadein 420ms ease-out;
	}

	.hero h1 {
		font-size: clamp(1.5rem, 3vw, 2.1rem);
		margin: 0 0 0.35rem;
	}

	.hero p {
		margin: 0;
		opacity: 0.85;
	}

	.panel {
		border: 1px solid rgba(98, 184, 255, 0.32);
		border-radius: 1rem;
		background: rgba(9, 24, 42, 0.84);
		padding: 1rem;
		animation: fadeup 380ms ease-out;
	}

	.panel-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.8rem;
		margin-bottom: 0.85rem;
	}

	.panel-head h2 {
		margin: 0;
		font-size: 1.05rem;
	}

	.grid {
		display: grid;
		gap: 0.7rem;
	}

	.two-col {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}

	.three-col {
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}

	label {
		font-size: 0.79rem;
		opacity: 0.92;
		display: block;
		margin-bottom: 0.2rem;
	}

	.field-label {
		font-size: 0.79rem;
		opacity: 0.92;
		display: block;
		margin: 0 0 0.2rem;
	}

	input,
	textarea,
	button,
	pre {
		font-family: 'IBM Plex Mono', 'Menlo', 'Consolas', monospace;
	}

	input,
	textarea {
		width: 100%;
		border: 1px solid rgba(118, 195, 255, 0.5);
		background: rgba(7, 17, 33, 0.85);
		color: #f2f9ff;
		border-radius: 0.5rem;
		padding: 0.52rem 0.58rem;
		box-sizing: border-box;
	}

	textarea {
		min-height: 180px;
		resize: vertical;
	}

	button {
		border: 1px solid rgba(107, 207, 255, 0.55);
		background: linear-gradient(145deg, #0f79bf, #0a5ea7);
		color: #eaf7ff;
		border-radius: 0.5rem;
		padding: 0.48rem 0.75rem;
		cursor: pointer;
		transition: transform 160ms ease, filter 160ms ease;
	}

	button:hover {
		transform: translateY(-1px);
		filter: brightness(1.08);
	}

	button.secondary,
	button.chip {
		background: linear-gradient(145deg, #1f355a, #182b4b);
		border-color: rgba(149, 186, 255, 0.42);
	}

	button.submit {
		background: linear-gradient(145deg, #11a5dd, #0b7ec7);
		border-color: rgba(118, 224, 255, 0.68);
	}

	button.danger {
		background: linear-gradient(145deg, #a83252, #7d1f3a);
		border-color: rgba(255, 154, 180, 0.68);
	}

	button:disabled {
		cursor: not-allowed;
		filter: grayscale(0.6);
		opacity: 0.5;
		transform: none;
	}

	.action-state {
		display: inline-block;
		margin-left: 0.4rem;
		color: #ffd1dc;
		font-size: 0.7rem;
	}

	button.selected,
	tr.selected {
		outline: 1px solid rgba(109, 214, 255, 0.95);
	}

	.row {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		flex-wrap: wrap;
	}

	.inline {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}

	.preset-row {
		display: flex;
		gap: 0.6rem;
		flex-wrap: wrap;
		margin-bottom: 0.8rem;
	}

	.toggle-grid {
		display: grid;
		gap: 0.4rem;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		margin-top: 0.7rem;
	}

	.toggle-grid label {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		margin: 0;
	}

	.profile-list {
		display: grid;
		gap: 0.4rem;
		max-height: 220px;
		overflow: auto;
		padding-right: 0.2rem;
		margin-bottom: 0.6rem;
	}

	.table-wrap {
		overflow: auto;
		border-radius: 0.6rem;
		border: 1px solid rgba(119, 186, 255, 0.34);
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.78rem;
	}

	th,
	td {
		padding: 0.45rem 0.52rem;
		border-bottom: 1px solid rgba(119, 154, 191, 0.25);
		text-align: left;
		white-space: nowrap;
	}

	.status {
		padding: 0.1rem 0.36rem;
		border-radius: 0.34rem;
		font-size: 0.72rem;
		border: 1px solid rgba(173, 223, 255, 0.28);
	}

	.status.completed {
		background: rgba(0, 190, 255, 0.24);
	}

	.status.failed,
	.status.cancelled {
		background: rgba(189, 53, 78, 0.36);
	}

	.status.running {
		background: rgba(59, 127, 255, 0.34);
	}

	pre {
		overflow: auto;
		background: rgba(6, 14, 27, 0.9);
		border: 1px solid rgba(111, 172, 224, 0.38);
		padding: 0.65rem;
		border-radius: 0.6rem;
		font-size: 0.74rem;
	}

	.muted {
		opacity: 0.73;
		font-size: 0.8rem;
	}

	.hint {
		opacity: 0.72;
		font-size: 0.72rem;
		line-height: 1.35;
		margin: 0.28rem 0 0;
	}

	.ok {
		color: #6de7ff;
	}

	.error {
		color: #ff9ab4;
	}

	@media (max-width: 980px) {
		.two-col,
		.three-col,
		.toggle-grid {
			grid-template-columns: 1fr;
		}

		.panel-head {
			flex-direction: column;
			align-items: flex-start;
		}
	}

	@keyframes fadein {
		from {
			opacity: 0;
			transform: translateY(7px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	@keyframes fadeup {
		from {
			opacity: 0;
			transform: translateY(10px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
</style>
