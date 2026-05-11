import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getJob, getProfile, getTask } from '$lib/api';

export const load: PageLoad = async ({ params }) => {
	const job = await getJob(params.jobId);
	if (!job) error(404, 'Job not found');

	const task = await getTask(job.taskId);
	const profile = await getProfile(job.profileId);

	return { job, task, profile };
};
