import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getJob, getJobSummary, getProfile, getTask } from '$lib/api';
import type { Job, JobResultSummary } from '$lib/api/types';

function fallbackJob(jobId: string, summary: JobResultSummary): Job {
	const profileId = jobId.replace(/_\d+$/, '') || 'crawler';
	return {
		id: jobId,
		taskId: `manual-${profileId}`,
		profileId,
		status: summary.status ?? 'completed',
		startTime: summary.startedAt ?? new Date().toISOString(),
		endTime: summary.completedAt,
		log: [],
		failedPages: summary.failedUrls
	};
}

export const load: PageLoad = async ({ params, fetch }) => {
	const summary = await getJobSummary(params.jobId, fetch);
	const job = (await getJob(params.jobId, fetch)) ?? (summary ? fallbackJob(params.jobId, summary) : undefined);
	if (!job) error(404, 'Job not found');

	const task = job.taskId === 'crawler-job' ? undefined : await getTask(job.taskId, fetch);
	const profile = job.profileId === 'crawler' ? undefined : await getProfile(job.profileId, fetch);

	return { job, task, profile, summary };
};
