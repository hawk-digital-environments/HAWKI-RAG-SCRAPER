import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getProfile, getProfileTasks } from '$lib/api';

export const load: PageLoad = async ({ params, fetch }) => {
	const profile = await getProfile(params.profileId, fetch);
	if (!profile) error(404, 'Profile not found');
	return { profile, tasks: await getProfileTasks(profile.id, fetch) };
};
