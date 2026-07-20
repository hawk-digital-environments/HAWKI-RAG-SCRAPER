import type { PageLoad } from './$types';
import { getAllProfiles, getAllTasks, getDashboardJobs } from '$lib/api';
import type { Job } from '$lib/api/types';

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : 'Failed to load jobs';
}

export const load: PageLoad = async ({ fetch }) => {
	let jobs: Job[] = [];
	let jobsError: string | null = null;

	try {
		jobs = await getDashboardJobs(fetch);
	} catch (error) {
		jobsError = errorMessage(error);
	}

	return {
		jobs,
		jobsError,
		tasks: await getAllTasks(fetch),
		profiles: await getAllProfiles(fetch)
	};
};
