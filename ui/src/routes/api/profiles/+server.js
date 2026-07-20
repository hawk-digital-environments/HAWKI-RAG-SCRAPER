// @ts-nocheck
import fs from 'node:fs/promises';
import path from 'node:path';

import { json } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';

const NAME_PATTERN = /^[A-Za-z0-9._-]+$/;
const profilesHostDir = env.PROFILES_HOST_DIR ?? path.resolve(process.cwd(), '..', 'profiles');
const profilesContainerDir = env.PROFILES_CONTAINER_DIR ?? '/var/www/html/profiles';

function normalizeName(raw) {
	if (typeof raw !== 'string') {
		return null;
	}
	const base = raw.trim().replace(/\.json(?:\.example)?$/i, '');
	if (!base || !NAME_PATTERN.test(base)) {
		return null;
	}
	return base;
}

function profileFilePath(name) {
	return path.join(profilesHostDir, `${name}.json`);
}

function profileContainerPath(name) {
	return `${profilesContainerDir}/${name}.json`;
}

async function readJsonProfile(filePath) {
	const text = await fs.readFile(filePath, 'utf-8');
	const parsed = JSON.parse(text);
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
		return {};
	}
	return parsed;
}

export async function GET() {
	await fs.mkdir(profilesHostDir, { recursive: true });
	const entries = await fs.readdir(profilesHostDir, { withFileTypes: true });
	const files = entries
		.filter((entry) => entry.isFile() && (entry.name.endsWith('.json') || entry.name.endsWith('.json.example')))
		.sort((a, b) => a.name.localeCompare(b.name));

	const profiles = [];
	for (const file of files) {
		const cleanedName = normalizeName(file.name);
		if (!cleanedName) {
			continue;
		}
		const fullPath = path.join(profilesHostDir, file.name);
		try {
			const profile = await readJsonProfile(fullPath);
			profiles.push({
				name: cleanedName,
				hostPath: fullPath,
				containerPath: profileContainerPath(cleanedName),
				match_hosts: Array.isArray(profile.match_hosts) ? profile.match_hosts : [],
				profile,
				readonlyExample: file.name.endsWith('.json.example')
			});
		} catch {
			profiles.push({
				name: cleanedName,
				hostPath: fullPath,
				containerPath: profileContainerPath(cleanedName),
				match_hosts: [],
				profile: {},
				readonlyExample: file.name.endsWith('.json.example')
			});
		}
	}

	return json({ profiles });
}

export async function POST({ request }) {
	let body;
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const incoming = body && typeof body === 'object' ? body : {};
	const candidateName = incoming.name || incoming.profile?.name;
	const name = normalizeName(candidateName);
	if (!name) {
		return json({ error: 'Invalid profile name. Use letters, numbers, dot, underscore, hyphen.' }, { status: 400 });
	}

	const content = incoming.profile;
	if (!content || typeof content !== 'object' || Array.isArray(content)) {
		return json({ error: 'profile must be a JSON object' }, { status: 400 });
	}

	await fs.mkdir(profilesHostDir, { recursive: true });
	const targetPath = profileFilePath(name);
	await fs.writeFile(targetPath, `${JSON.stringify(content, null, 2)}\n`, 'utf-8');

	return json({
		name,
		hostPath: targetPath,
		containerPath: profileContainerPath(name),
		match_hosts: Array.isArray(content.match_hosts) ? content.match_hosts : [],
		profile: content,
		readonlyExample: false
	});
}
