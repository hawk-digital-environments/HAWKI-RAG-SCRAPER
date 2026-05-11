import { env } from '$env/dynamic/public';
import type { Job, JobStatus, Profile, ProfileInput, Queue, Task, TaskInput } from './types';

type ApiFetch = typeof fetch;

type ProfileEntry = {
	name: string;
	hostPath: string;
	containerPath: string;
	match_hosts: string[];
	profile: Record<string, unknown>;
	readonlyExample?: boolean;
};

type CrawlerJobStatus = {
	job_id: string;
	status?: string;
	message?: string;
	pages_crawled?: number;
	total_pages?: number;
	started_at?: string;
	completed_at?: string;
	output_directory?: string;
};

type QueueEntry = {
	name: string;
	messages?: number;
	messages_ready?: number;
	messages_unacknowledged?: number;
};

export class ApiError extends Error {
	constructor(
		message: string,
		readonly status: number,
		readonly body: unknown
	) {
		super(message);
		this.name = 'ApiError';
	}
}

const apiBaseUrl = (env.PUBLIC_API_BASE_URL ?? '').replace(/\/$/, '');

function endpoint(path: string): string {
	return `${apiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`;
}

async function request<T>(path: string, init?: RequestInit, apiFetch: ApiFetch = fetch): Promise<T> {
	const response = await apiFetch(endpoint(path), {
		...init,
		headers: {
			...(init?.body ? { 'content-type': 'application/json' } : {}),
			...init?.headers
		}
	});

	const contentType = response.headers.get('content-type') ?? '';
	const body = contentType.includes('application/json') ? await response.json() : await response.text();

	if (!response.ok) {
		const message =
			typeof body === 'object' && body && 'error' in body
				? String((body as { error: unknown }).error)
				: `API request failed with status ${response.status}`;
		throw new ApiError(message, response.status, body);
	}

	return body as T;
}

function asStringArray(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function profileName(profile: Record<string, unknown>, fallback: string): string {
	return typeof profile.name === 'string' && profile.name.trim() ? profile.name : fallback;
}

function profileToUi(entry: ProfileEntry): Profile {
	const profile = entry.profile ?? {};
	const sitemap = profile.sitemap && typeof profile.sitemap === 'object' ? profile.sitemap as Record<string, unknown> : {};
	const discovery = profile.discovery && typeof profile.discovery === 'object' ? profile.discovery as Record<string, unknown> : {};
	const forbidden = profile.forbidden && typeof profile.forbidden === 'object' ? profile.forbidden as Record<string, unknown> : {};
	const content = profile.content && typeof profile.content === 'object' ? profile.content as Record<string, unknown> : {};

	const hostEntrypoints = entry.match_hosts
		.filter((host) => !host.startsWith('*.'))
		.map((host) => ({ type: 'host' as const, src: host }));
	const sitemapBase = typeof sitemap.base_url === 'string' ? sitemap.base_url : '';

	return {
		id: entry.name,
		name: profileName(profile, entry.name),
		entrypoints: sitemapBase ? [...hostEntrypoints, { type: 'sitemap', src: sitemapBase }] : hostEntrypoints,
		discovery: { hosts: asStringArray(discovery.allowed_hosts ?? discovery.hosts) },
		forbidden: {
			hosts: asStringArray(forbidden.hosts),
			url_patterns: asStringArray(forbidden.url_patterns)
		},
		content: {
			content_selectors: asStringArray(content.content_selectors),
			noise_phrases: asStringArray(content.noise_phrases),
			noise_patterns: asStringArray(content.noise_patterns),
			tag_selectors: asStringArray(content.tag_selectors)
		},
		max_execution_time: typeof profile.max_execution_time === 'string' ? profile.max_execution_time : '24h',
		max_storage_time: typeof profile.max_storage_time === 'string' ? profile.max_storage_time : '7d',
		rescrape_failed: typeof profile.rescrape_failed === 'boolean' ? profile.rescrape_failed : false
	};
}

function profileInputToBackend(input: ProfileInput): Record<string, unknown> {
	const hostEntrypoints = input.entrypoints.filter((entry) => entry.type === 'host');
	const sitemapEntrypoint = input.entrypoints.find((entry) => entry.type === 'sitemap');

	return {
		name: input.name,
		match_hosts: hostEntrypoints.map((entry) => entry.src),
		discovery: input.discovery ? { allowed_hosts: input.discovery.hosts ?? [] } : undefined,
		forbidden: input.forbidden,
		content: input.content,
		sitemap:
			sitemapEntrypoint?.type === 'sitemap'
				? {
						enabled: true,
						base_url: sitemapEntrypoint.src,
						start_page: 1,
						pages: 1,
						output_path: `data/${input.name}_sitemap.json`
					}
				: undefined,
		max_execution_time: input.max_execution_time,
		max_storage_time: input.max_storage_time,
		rescrape_failed: input.rescrape_failed
	};
}

function taskForProfile(profile: Profile): Task {
	return {
		id: `manual-${profile.id}`,
		name: `${profile.name} Manual Crawl`,
		profileId: profile.id
	};
}

function normalizeStatus(status: unknown): JobStatus {
	const value = typeof status === 'string' ? status.toLowerCase() : 'running';
	if (value === 'completed' || value === 'failed' || value === 'cancelled' || value === 'stopping') {
		return value;
	}
	return 'running';
}

function jobToUi(job: CrawlerJobStatus): Job {
	const status = normalizeStatus(job.status);
	const started = job.started_at ?? new Date().toISOString();
	const log = [
		`[${started}] ${status.toUpperCase()} ${job.message ?? 'Crawler job status loaded'}`,
		`Pages crawled: ${job.pages_crawled ?? 0} / ${job.total_pages ?? 0}`
	];

	return {
		id: job.job_id,
		taskId: 'crawler-job',
		profileId: 'crawler',
		status,
		startTime: started,
		endTime: job.completed_at,
		log,
		failedPages: []
	};
}

export async function getAllProfiles(apiFetch?: ApiFetch): Promise<Profile[]> {
	const payload = await request<{ profiles?: ProfileEntry[] }>('/api/profiles', undefined, apiFetch);
	return (payload.profiles ?? []).map(profileToUi);
}

export async function getProfile(id: string, apiFetch?: ApiFetch): Promise<Profile | undefined> {
	try {
		const entry = await request<ProfileEntry>(`/api/profiles/${encodeURIComponent(id)}`, undefined, apiFetch);
		return profileToUi(entry);
	} catch (error) {
		if (error instanceof ApiError && error.status === 404) return undefined;
		throw error;
	}
}

export async function createProfile(input: ProfileInput): Promise<Profile> {
	const entry = await request<ProfileEntry>('/api/profiles', {
		method: 'POST',
		body: JSON.stringify({ name: input.name, profile: profileInputToBackend(input) })
	});
	return profileToUi(entry);
}

export async function updateProfile(id: string, input: ProfileInput): Promise<Profile | undefined> {
	const entry = await request<ProfileEntry>(`/api/profiles/${encodeURIComponent(id)}`, {
		method: 'PUT',
		body: JSON.stringify({ profile: profileInputToBackend(input) })
	});
	return profileToUi(entry);
}

export async function deleteProfile(id: string): Promise<boolean> {
	await request(`/api/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' });
	return true;
}

export async function getProfileTaskCount(profileId: string, apiFetch?: ApiFetch): Promise<number> {
	return (await getProfileTasks(profileId, apiFetch)).length;
}

export async function getProfileTasks(profileId: string, apiFetch?: ApiFetch): Promise<Task[]> {
	const profile = await getProfile(profileId, apiFetch);
	return profile ? [taskForProfile(profile)] : [];
}

export async function getAllTasks(apiFetch?: ApiFetch): Promise<Task[]> {
	return (await getAllProfiles(apiFetch)).map(taskForProfile);
}

export async function getTask(id: string, apiFetch?: ApiFetch): Promise<Task | undefined> {
	const profiles = await getAllProfiles(apiFetch);
	const profile = profiles.find((item) => `manual-${item.id}` === id || item.id === id);
	return profile ? taskForProfile(profile) : undefined;
}

export async function createTask(input: TaskInput): Promise<Task> {
	return { ...input, id: `manual-${input.profileId}` };
}

export async function updateTask(id: string, input: TaskInput): Promise<Task | undefined> {
	return { ...input, id };
}

export async function deleteTask(_id: string): Promise<boolean> {
	return true;
}

export async function getAllJobs(apiFetch?: ApiFetch): Promise<Job[]> {
	try {
		const payload = await request<{ jobs?: Record<string, CrawlerJobStatus> | CrawlerJobStatus[] }>('/api/crawler/jobs', undefined, apiFetch);
		const jobs = Array.isArray(payload.jobs) ? payload.jobs : Object.values(payload.jobs ?? {});
		return jobs.filter((job): job is CrawlerJobStatus => !!job?.job_id).map(jobToUi);
	} catch (error) {
		if (error instanceof ApiError) return [];
		throw error;
	}
}

export async function getRunningJobs(apiFetch?: ApiFetch): Promise<Job[]> {
	return (await getAllJobs(apiFetch)).filter((job) => job.status === 'running' || job.status === 'stopping');
}

export async function getJob(id: string, apiFetch?: ApiFetch): Promise<Job | undefined> {
	return (await getAllJobs(apiFetch)).find((job) => job.id === id);
}

export async function startJob(taskId: string): Promise<Job> {
	const task = await getTask(taskId);
	if (!task) throw new Error(`Task ${taskId} not found`);

	const profileEntry = await request<ProfileEntry>(`/api/profiles/${encodeURIComponent(task.profileId)}`);
	const profile = profileToUi(profileEntry);
	const firstHost = profile.entrypoints.find((entry) => entry.type === 'host')?.src;
	const firstSitemap = profile.entrypoints.find((entry) => entry.type === 'sitemap')?.src;
	const response = await request<Record<string, unknown>>('/api/crawler/submit', {
		method: 'POST',
		body: JSON.stringify({
			job_id: `${task.profileId}_${Date.now()}`,
			url: firstHost ? `https://${firstHost}` : firstSitemap,
			output_dir: 'output',
			site_profile_path: profileEntry.containerPath,
			rescrape_failed: profile.rescrape_failed,
			sitemap: !!firstSitemap,
			sitemap_base: firstSitemap,
			max_pages: 0,
			max_concurrency: 1,
			max_rpm: 20
		})
	});

	const jobId = typeof response.job_id === 'string' ? response.job_id : `${task.profileId}_${Date.now()}`;
	return {
		id: jobId,
		taskId: task.id,
		profileId: profile.id,
		status: 'running',
		startTime: new Date().toISOString(),
		log: [`Job submitted for ${profile.name}`],
		failedPages: []
	};
}

export async function stopJob(id: string): Promise<Job | undefined> {
	await request(`/api/crawler/job/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
	return getJob(id);
}

export async function finalizeStopJob(id: string): Promise<Job | undefined> {
	return getJob(id);
}

export async function retryJob(originalJobId: string): Promise<Job> {
	const original = await getJob(originalJobId);
	if (!original) throw new Error(`Job ${originalJobId} not found`);
	throw new Error('Retrying failed pages is not supported by the current crawler API.');
}

export async function restartJob(originalJobId: string): Promise<Job> {
	const original = await getJob(originalJobId);
	if (!original) throw new Error(`Job ${originalJobId} not found`);
	throw new Error('Restarting jobs is not supported by the current crawler API.');
}

export async function getQueues(apiFetch?: ApiFetch): Promise<Queue[]> {
	try {
		const payload = await request<{ queues?: QueueEntry[] }>('/api/rabbitmq/queues', undefined, apiFetch);
		return (payload.queues ?? []).map((queue) => ({
			name: queue.name,
			ready: queue.messages_ready ?? 0,
			unacked: queue.messages_unacknowledged ?? 0,
			total: queue.messages ?? 0
		}));
	} catch (error) {
		if (error instanceof ApiError) return [];
		throw error;
	}
}
