import type { PageLoad } from './$types';
import { getAllProfiles } from '$lib/api';

export const load: PageLoad = async ({ url, fetch }) => {
	return {
		profiles: await getAllProfiles(fetch),
		preselectedProfileId: url.searchParams.get('profileId') ?? undefined
	};
};
