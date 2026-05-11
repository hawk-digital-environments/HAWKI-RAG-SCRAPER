import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getTask, getAllProfiles } from '$lib/api';

export const load: PageLoad = async ({ params, fetch }) => {
	const task = await getTask(params.taskId, fetch);
	if (!task) error(404, 'Task not found');
	return { task, profiles: await getAllProfiles(fetch) };
};
