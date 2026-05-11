import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getTask, getProfile, getAllJobs } from '$lib/api';

export const load: PageLoad = async ({ params }) => {
	const task = await getTask(params.taskId);
	if (!task) error(404, 'Task not found');

	const profile = await getProfile(task.profileId);
	const jobs = (await getAllJobs())
		.filter((j) => j.taskId === task.id)
		.sort((a, b) => new Date(b.startTime).getTime() - new Date(a.startTime).getTime())
		.slice(0, 5);

	return { task, profile, recentJobs: jobs };
};
