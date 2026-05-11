import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getTask, getAllProfiles } from '$lib/api';

export const load: PageLoad = async ({ params }) => {
	const task = await getTask(params.taskId);
	if (!task) error(404, 'Task not found');
	return { task, profiles: await getAllProfiles() };
};
