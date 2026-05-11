import type { PageLoad } from './$types';
import { getAllProfiles, getAllTasks } from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
	return {
		tasks: await getAllTasks(fetch),
		profiles: await getAllProfiles(fetch)
	};
};
