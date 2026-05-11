import type { PageLoad } from './$types';
import { getAllProfiles, getAllTasks } from '$lib/api';

export const load: PageLoad = async () => {
	return {
		tasks: await getAllTasks(),
		profiles: await getAllProfiles()
	};
};
