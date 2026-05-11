import type { PageLoad } from './$types';
import { getAllProfiles } from '$lib/api';

export const load: PageLoad = async ({ url }) => {
	return {
		profiles: await getAllProfiles(),
		preselectedProfileId: url.searchParams.get('profileId') ?? undefined
	};
};
