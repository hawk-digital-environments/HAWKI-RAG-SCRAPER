// @ts-nocheck
import fs from 'node:fs/promises';
import path from 'node:path';

import { json } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';

const NAME_PATTERN = /^[A-Za-z0-9._-]+$/;
const profilesHostDir = env.PROFILES_HOST_DIR ?? path.resolve(process.cwd(), '..', 'profiles');
const profilesContainerDir = env.PROFILES_CONTAINER_DIR ?? '/app/profiles';

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

async function readProfile(name) {
	const filePath = profileFilePath(name);
	const text = await fs.readFile(filePath, 'utf-8');
	const profile = JSON.parse(text);
	return {
		name,
		hostPath: filePath,
		containerPath: profileContainerPath(name),
		match_hosts: Array.isArray(profile.match_hosts) ? profile.match_hosts : [],
		profile,
		readonlyExample: false
	};
}

export async function GET({ params }) {
	const name = normalizeName(params.name);
	if (!name) {
		return json({ error: 'Invalid profile name' }, { status: 400 });
	}

	try {
		return json(await readProfile(name));
	} catch {
		const examplePath = path.join(profilesHostDir, `${name}.json.example`);
		try {
			const text = await fs.readFile(examplePath, 'utf-8');
			const profile = JSON.parse(text);
			return json({
				name,
				hostPath: examplePath,
				containerPath: profileContainerPath(name),
				match_hosts: Array.isArray(profile.match_hosts) ? profile.match_hosts : [],
				profile,
				readonlyExample: true
			});
		} catch (error) {
			return json({ error: `Profile read failed: ${error}` }, { status: 404 });
		}
	}
}

export async function PUT({ params, request }) {
	const name = normalizeName(params.name);
	if (!name) {
		return json({ error: 'Invalid profile name' }, { status: 400 });
	}

	let body;
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const content = body?.profile;
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

export async function DELETE({ params }) {
	const name = normalizeName(params.name);
	if (!name) {
		return json({ error: 'Invalid profile name' }, { status: 400 });
	}

	const targetPath = profileFilePath(name);
	try {
		await fs.unlink(targetPath);
		return json({ ok: true });
	} catch (error) {
		if (error && error.code === 'ENOENT') {
			return json(
				{ error: 'Profile file not found or is a readonly example profile' },
				{ status: 404 }
			);
		}
		return json({ error: `Profile delete failed: ${error}` }, { status: 500 });
	}
}
