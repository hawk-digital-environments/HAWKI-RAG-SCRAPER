import type { PageLoad } from './$types';
import { getAllProfiles, getAllTasks, getQueues, getRunningJobs } from '$lib/api';

export const load: PageLoad = async () => {
	return {
		runningJobs: await getRunningJobs(),
		tasks: await getAllTasks(),
		profiles: await getAllProfiles(),
		queues: await getQueues()
	};
};
