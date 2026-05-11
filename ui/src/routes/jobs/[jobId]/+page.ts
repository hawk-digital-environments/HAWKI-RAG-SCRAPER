import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getJob, getProfile, getTask } from '$lib/api';

export const load: PageLoad = async ({ params, fetch }) => {
	const job = await getJob(params.jobId, fetch);
	if (!job) error(404, 'Job not found');

	const task = job.taskId === 'crawler-job' ? undefined : await getTask(job.taskId, fetch);
	const profile = job.profileId === 'crawler' ? undefined : await getProfile(job.profileId, fetch);

	return { job, task, profile };
};
