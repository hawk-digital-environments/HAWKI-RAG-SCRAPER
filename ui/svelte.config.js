import adapter from '@sveltejs/adapter-node';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		adapter: adapter(),
		paths: {
			// Configurable at build time via the PUBLIC_API_BASE_URL build arg
			// (see the Dockerfile); falls back to the default public UI path.
			base: process.env.PUBLIC_API_BASE_URL || '/ui'
		}
	}
};

export default config;
