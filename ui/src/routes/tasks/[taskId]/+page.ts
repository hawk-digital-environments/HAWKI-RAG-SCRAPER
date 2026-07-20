import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getTask, getProfile, getAllJobs } from '$lib/api';

export const load: PageLoad = async ({ params, fetch }) => {
	const task = await getTask(params.taskId, fetch);
	if (!task) error(404, 'Task not found');

	const profile = await getProfile(task.profileId, fetch);
	const jobs = (await getAllJobs(fetch))
		.filter((j) => {
			return (
				j.taskId === task.id ||
				j.profileId === task.profileId ||
				j.id.startsWith(`${task.profileId}_`)
			);
		})
		.sort((a, b) => new Date(b.startTime).getTime() - new Date(a.startTime).getTime())
		.slice(0, 5);

	return { task, profile, recentJobs: jobs };
};
