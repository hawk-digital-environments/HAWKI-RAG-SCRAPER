import type { Job, JobStatus, Profile, ProfileInput, Queue, Task, TaskInput } from './types';

// ---------------------------------------------------------------------------
// Initial mock data
// ---------------------------------------------------------------------------

const initialProfiles: Profile[] = [
	{
		id: 'profile-hawk',
		name: 'HAWK University',
		entrypoints: [
			{ type: 'host', src: 'hawk.de' },
			{ type: 'sitemap', src: 'https://www.hawk.de/sitemap.xml' }
		],
		discovery: { hosts: ['haw.hamburg'] },
		forbidden: {
			hosts: ['login.hawk.de', 'mail.hawk.de', 'webmail.hawk.de'],
			url_patterns: ['/en/login', '/privacy', '/imprint', '/cookie-settings']
		},
		content: {
			content_selectors: ['.tx-content', 'main', 'article', '[role="main"]'],
			noise_phrases: ['cookie settings', 'share this page', 'back to top'],
			noise_patterns: ['breadcrumb', 'sidebar-right', 'footer-nav', 'social-share'],
			tag_selectors: ["meta[name='keywords']", "meta[property='article:tag']"]
		},
		max_execution_time: '12h',
		max_storage_time: '14d',
		rescrape_failed: true
	},
	{
		id: 'profile-archive',
		name: 'HAWK Research Archive',
		entrypoints: [
			{ type: 'host', src: 'archive.hawk.de', protocol: 'http' },
			{
				type: 'sitemap',
				src: 'https://archive.hawk.de/sitemap.xml',
				conflict_resolution: { last_modified: 'sitemap', language: 'sitemap' }
			}
		],
		max_execution_time: '48h',
		max_storage_time: '30d',
		rescrape_failed: false
	},
	{
		id: 'profile-partner',
		name: 'Partner Institute',
		entrypoints: [{ type: 'host', src: 'external-partner.edu' }],
		discovery: { hosts: ['docs.external-partner.edu'] },
		forbidden: {
			hosts: ['intranet.external-partner.edu'],
			url_patterns: ['/login', '/internal']
		},
		max_execution_time: '6h',
		max_storage_time: '7d',
		rescrape_failed: false
	}
];

const initialTasks: Task[] = [
	{
		id: 'task-hawk-weekly',
		name: 'HAWK Weekly Crawl',
		profileId: 'profile-hawk',
		schedule: '0 2 * * 1'
	},
	{
		id: 'task-hawk-manual',
		name: 'Manual HAWK Backup',
		profileId: 'profile-hawk'
	},
	{
		id: 'task-partner-daily',
		name: 'Daily Partner Sync',
		profileId: 'profile-partner',
		schedule: '0 3 * * *'
	},
	{
		id: 'task-archive',
		name: 'Archive Full Scan',
		profileId: 'profile-archive'
	}
];

const runningLog = [
	'[2026-05-08 10:30:01] INFO  Job started (id: job-001)',
	'[2026-05-08 10:30:02] INFO  Loading profile: HAWK University',
	'[2026-05-08 10:30:03] INFO  Fetching sitemap: https://www.hawk.de/sitemap.xml',
	'[2026-05-08 10:30:08] INFO  Sitemap parsed: 1248 URLs found',
	'[2026-05-08 10:30:09] INFO  Discovery started — seed queue: 1248 URLs',
	'[2026-05-08 10:31:22] INFO  Crawled: https://hawk.de/ (200)',
	'[2026-05-08 10:31:23] INFO  Crawled: https://hawk.de/studium (200)',
	'[2026-05-08 10:31:24] INFO  Crawled: https://hawk.de/forschung (200)',
	'[2026-05-08 10:32:01] INFO  Crawled: https://hawk.de/hochschule (200)',
	'[2026-05-08 10:33:14] INFO  Crawled: https://hawk.de/international (200)',
	'[2026-05-08 10:45:55] INFO  Queue depth: 892 remaining',
	'[2026-05-08 11:12:33] INFO  Queue depth: 441 remaining',
	'[2026-05-08 11:58:07] INFO  Queue depth: 123 remaining',
	'[2026-05-08 12:15:41] INFO  Crawled: https://hawk.de/studium/bewerbung (200)',
	'[2026-05-08 12:16:03] INFO  Crawled: https://hawk.de/studium/beratung (200)'
];

const completedLog = [
	'[2026-05-07 03:00:01] INFO  Job started (id: job-002)',
	'[2026-05-07 03:00:02] INFO  Loading profile: Partner Institute',
	'[2026-05-07 03:00:03] INFO  No sitemap configured — starting host discovery',
	'[2026-05-07 03:00:05] INFO  Discovery started — seed: https://external-partner.edu',
	'[2026-05-07 03:12:44] INFO  Crawled 340 pages',
	'[2026-05-07 04:33:12] INFO  Crawled 680 pages',
	'[2026-05-07 05:55:01] INFO  Discovery complete — 948 pages total',
	'[2026-05-07 06:10:22] INFO  File conversion queue drained',
	'[2026-05-07 06:14:51] INFO  RAG ingestion complete',
	'[2026-05-07 06:15:00] INFO  Job completed successfully'
];

const failedPagesLog = [
	'[2026-05-01 02:05:01] INFO  Job started (id: job-003)',
	'[2026-05-01 02:05:02] INFO  Loading profile: HAWK University',
	'[2026-05-01 02:05:04] INFO  Fetching sitemap: https://www.hawk.de/sitemap.xml',
	'[2026-05-01 02:05:09] INFO  Sitemap parsed: 1211 URLs found',
	'[2026-05-01 02:05:10] INFO  Discovery started — seed queue: 1211 URLs',
	'[2026-05-01 05:22:14] INFO  Crawled 600 pages',
	'[2026-05-01 07:44:01] INFO  Crawled 900 pages',
	'[2026-05-01 09:11:33] WARN  Failed to fetch: https://hawk.de/forschung/projekte (503)',
	'[2026-05-01 09:11:34] WARN  Failed to fetch: https://hawk.de/forschung/projekte (retry 1/3)',
	'[2026-05-01 09:11:45] WARN  Failed to fetch: https://hawk.de/forschung/projekte (retry 2/3)',
	'[2026-05-01 09:11:56] ERROR Page permanently failed: https://hawk.de/forschung/projekte',
	'[2026-05-01 09:44:21] WARN  Failed to fetch: https://hawk.de/studium/beratung (timeout)',
	'[2026-05-01 09:44:22] WARN  Failed to fetch: https://hawk.de/studium/beratung (retry 1/3)',
	'[2026-05-01 09:44:33] ERROR Page permanently failed: https://hawk.de/studium/beratung',
	'[2026-05-01 11:20:05] INFO  Discovery complete — 1198 pages total (2 failed)',
	'[2026-05-01 11:45:12] INFO  File conversion queue drained',
	'[2026-05-01 11:47:00] INFO  Job completed with 2 failed pages'
];

const failedJobLog = [
	'[2026-05-05 14:20:01] INFO  Job started (id: job-004)',
	'[2026-05-05 14:20:02] INFO  Loading profile: HAWK Research Archive',
	'[2026-05-05 14:20:03] INFO  Fetching sitemap: https://archive.hawk.de/sitemap.xml',
	'[2026-05-05 14:20:08] ERROR Connection refused: archive.hawk.de (ECONNREFUSED)',
	'[2026-05-05 14:20:09] INFO  Retrying connection (1/3)...',
	'[2026-05-05 14:20:39] ERROR Connection refused: archive.hawk.de (ECONNREFUSED)',
	'[2026-05-05 14:21:09] ERROR Connection refused: archive.hawk.de (ECONNREFUSED)',
	'[2026-05-05 14:21:10] FATAL All retries exhausted — runner process exiting',
	'[2026-05-05 14:21:11] INFO  Job failed'
];

const cancelledLog = [
	'[2026-04-30 09:00:01] INFO  Job started (id: job-005)',
	'[2026-04-30 09:00:02] INFO  Loading profile: Manual HAWK Backup',
	'[2026-04-30 09:00:04] INFO  Discovery started',
	'[2026-04-30 09:22:44] INFO  Crawled 200 pages',
	'[2026-04-30 10:44:01] INFO  Crawled 450 pages',
	'[2026-04-30 11:29:58] INFO  Received stop signal',
	'[2026-04-30 11:30:00] INFO  Job cancelled by user'
];

const initialJobs: Job[] = [
	{
		id: 'job-001',
		taskId: 'task-hawk-weekly',
		profileId: 'profile-hawk',
		status: 'running',
		startTime: '2026-05-08T10:30:00.000Z',
		log: [...runningLog],
		failedPages: []
	},
	{
		id: 'job-002',
		taskId: 'task-partner-daily',
		profileId: 'profile-partner',
		status: 'completed',
		startTime: '2026-05-07T03:00:00.000Z',
		endTime: '2026-05-07T06:15:00.000Z',
		log: completedLog,
		failedPages: []
	},
	{
		id: 'job-003',
		taskId: 'task-hawk-weekly',
		profileId: 'profile-hawk',
		status: 'completed',
		startTime: '2026-05-01T02:05:00.000Z',
		endTime: '2026-05-01T11:47:00.000Z',
		log: failedPagesLog,
		failedPages: ['https://hawk.de/forschung/projekte', 'https://hawk.de/studium/beratung']
	},
	{
		id: 'job-004',
		taskId: 'task-archive',
		profileId: 'profile-archive',
		status: 'failed',
		startTime: '2026-05-05T14:20:00.000Z',
		endTime: '2026-05-05T14:21:11.000Z',
		log: failedJobLog,
		failedPages: []
	},
	{
		id: 'job-005',
		taskId: 'task-hawk-manual',
		profileId: 'profile-hawk',
		status: 'cancelled',
		startTime: '2026-04-30T09:00:00.000Z',
		endTime: '2026-04-30T11:30:00.000Z',
		log: cancelledLog,
		failedPages: [],
		dataExpired: true
	}
];

const BUILT_IN_QUEUES: Queue[] = [
	{ name: 'file_conversion_jobs', ready: 0, unacked: 3, total: 3 },
	{ name: 'file_conversion_jobs_retry', ready: 0, unacked: 0, total: 0 },
	{ name: 'rag_ingestion_jobs', ready: 12, unacked: 5, total: 17 },
	{ name: 'rag_ingestion_jobs_retry', ready: 2, unacked: 0, total: 2 }
];

// ---------------------------------------------------------------------------
// In-memory store
// ---------------------------------------------------------------------------

const profiles = new Map<string, Profile>(initialProfiles.map((p) => [p.id, p]));
const tasks = new Map<string, Task>(initialTasks.map((t) => [t.id, t]));
const jobs = new Map<string, Job>(initialJobs.map((j) => [j.id, j]));

let idCounter = 100;
function newId(prefix: string): string {
	return `${prefix}-${++idCounter}`;
}

// ---------------------------------------------------------------------------
// Profile operations
// ---------------------------------------------------------------------------

export function getAllProfiles(): Profile[] {
	return [...profiles.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function getProfile(id: string): Profile | undefined {
	return profiles.get(id);
}

export function createProfile(input: ProfileInput): Profile {
	const profile: Profile = { ...input, id: newId('profile') };
	profiles.set(profile.id, profile);
	return profile;
}

export function updateProfile(id: string, input: ProfileInput): Profile | undefined {
	if (!profiles.has(id)) return undefined;
	const profile: Profile = { ...input, id };
	profiles.set(id, profile);
	return profile;
}

export function deleteProfile(id: string): boolean {
	return profiles.delete(id);
}

export function getProfileTaskCount(profileId: string): number {
	return [...tasks.values()].filter((t) => t.profileId === profileId).length;
}

export function getProfileTasks(profileId: string): Task[] {
	return [...tasks.values()].filter((t) => t.profileId === profileId);
}

// ---------------------------------------------------------------------------
// Task operations
// ---------------------------------------------------------------------------

export function getAllTasks(): Task[] {
	return [...tasks.values()];
}

export function getTask(id: string): Task | undefined {
	return tasks.get(id);
}

export function createTask(input: TaskInput): Task {
	const task: Task = { ...input, id: newId('task') };
	tasks.set(task.id, task);
	return task;
}

export function updateTask(id: string, input: TaskInput): Task | undefined {
	if (!tasks.has(id)) return undefined;
	const task: Task = { ...input, id };
	tasks.set(id, task);
	return task;
}

export function deleteTask(id: string): boolean {
	return tasks.delete(id);
}

// ---------------------------------------------------------------------------
// Job operations
// ---------------------------------------------------------------------------

export function getAllJobs(): Job[] {
	return [...jobs.values()];
}

export function getRunningJobs(): Job[] {
	return [...jobs.values()].filter((j) => j.status === 'running' || j.status === 'stopping');
}

export function getJob(id: string): Job | undefined {
	return jobs.get(id);
}

export function startJob(taskId: string): Job {
	const task = tasks.get(taskId);
	if (!task) throw new Error(`Task ${taskId} not found`);

	const job: Job = {
		id: newId('job'),
		taskId,
		profileId: task.profileId,
		status: 'running',
		startTime: new Date().toISOString(),
		log: [`[${new Date().toISOString()}] INFO  Job started`, `[${new Date().toISOString()}] INFO  Loading profile: ${profiles.get(task.profileId)?.name ?? task.profileId}`],
		failedPages: []
	};
	jobs.set(job.id, job);
	return job;
}

export function stopJob(id: string): Job | undefined {
	const job = jobs.get(id);
	if (!job || job.status !== 'running') return job;
	const updated: Job = { ...job, status: 'stopping' };
	jobs.set(id, updated);
	return updated;
}

export function finalizeStopJob(id: string): Job | undefined {
	const job = jobs.get(id);
	if (!job || job.status !== 'stopping') return job;
	const updated: Job = {
		...job,
		status: 'cancelled',
		endTime: new Date().toISOString(),
		log: [...job.log, `[${new Date().toISOString()}] INFO  Job cancelled by user`]
	};
	jobs.set(id, updated);
	return updated;
}

export function retryJob(originalJobId: string): Job {
	const original = jobs.get(originalJobId);
	if (!original) throw new Error(`Job ${originalJobId} not found`);
	const task = tasks.get(original.taskId);
	if (!task) throw new Error(`Task ${original.taskId} not found`);

	const job: Job = {
		id: newId('job'),
		taskId: original.taskId,
		profileId: original.profileId,
		status: 'running',
		startTime: new Date().toISOString(),
		log: [
			`[${new Date().toISOString()}] INFO  Retry job started (original: ${originalJobId})`,
			`[${new Date().toISOString()}] INFO  rescrape_failed=true — ${original.failedPages?.length ?? 0} pages queued for retry`,
			`[${new Date().toISOString()}] INFO  No new discovery — retrying failed pages only`
		],
		failedPages: []
	};
	jobs.set(job.id, job);
	return job;
}

export function restartJob(originalJobId: string): Job {
	const original = jobs.get(originalJobId);
	if (!original) throw new Error(`Job ${originalJobId} not found`);
	const task = tasks.get(original.taskId);
	if (!task) throw new Error(`Task ${original.taskId} not found`);
	const profile = profiles.get(original.profileId);

	const job: Job = {
		id: newId('job'),
		taskId: original.taskId,
		profileId: original.profileId,
		status: 'running',
		startTime: new Date().toISOString(),
		log: [
			`[${new Date().toISOString()}] INFO  Job restarted (previous: ${originalJobId})`,
			`[${new Date().toISOString()}] INFO  Loading profile: ${profile?.name ?? original.profileId}`
		],
		failedPages: []
	};
	jobs.set(job.id, job);
	return job;
}

export function appendJobLog(id: string, line: string): void {
	const job = jobs.get(id);
	if (!job) return;
	jobs.set(id, { ...job, log: [...job.log, line] });
}

// ---------------------------------------------------------------------------
// Queue operations
// ---------------------------------------------------------------------------

export function getQueues(): Queue[] {
	const runningQueues: Queue[] = getRunningJobs()
		.filter((j) => j.status === 'running')
		.map((j) => ({
			name: `job-${j.id}`,
			ready: Math.floor(Math.random() * 60) + 10,
			unacked: Math.floor(Math.random() * 15) + 1,
			total: 0
		}))
		.map((q) => ({ ...q, total: q.ready + q.unacked }));

	return [...BUILT_IN_QUEUES, ...runningQueues];
}
