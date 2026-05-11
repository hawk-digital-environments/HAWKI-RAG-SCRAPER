import type { PageLoad } from './$types';
import { getAllProfiles } from '$lib/api';

export const load: PageLoad = async () => {
	return {
		profiles: await getAllProfiles()
	};
};
