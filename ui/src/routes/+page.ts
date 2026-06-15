import type { PageLoad } from './$types';
import { getAllProfiles, getAllTasks, getRunningJobs } from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
	return {
        runningJobs: await getRunningJobs(fetch),
        tasks: await getAllTasks(fetch),
        profiles: await getAllProfiles(fetch)
    };
};
