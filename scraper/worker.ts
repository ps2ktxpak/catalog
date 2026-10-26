// Starts, watches and stops the scraper's containers. One Durable Object per shard, named "shard-<i>";
// each remembers whether its shard was asked to run, so the cron can restart one that stopped early.
//
//   GET  /status                       every shard's state and progress (public: it shows only counts)
//   POST /run    (Bearer RUN_TOKEN)    start every shard; finished packs are skipped, so this resumes
//   POST /stop   (Bearer RUN_TOKEN)    stop every shard

import { Container, getContainer } from '@cloudflare/containers';

// The bindings and vars come from wrangler.jsonc (`wrangler types`); these are the secrets.
declare global {
	interface Env {
		R2_ACCOUNT_ID: string;
		R2_ACCESS_KEY_ID: string;
		R2_SECRET_ACCESS_KEY: string;
		MEGA_USERNAME: string;
		MEGA_PASSWORD: string;
		RUN_TOKEN: string;
	}
}

export class Scraper extends Container<Env> {
	defaultPort = 8080;
	// The cron asks every ten minutes, which counts as activity; this only stops a shard nobody watches.
	sleepAfter = '45m';

	async begin(shard: number, shards: number): Promise<void> {
		await this.ctx.storage.put('wanted', { shard, shards });
		await this.launch();
	}

	async end(): Promise<void> {
		await this.ctx.storage.delete('wanted');
		await this.stop();
	}

	// The shard's own status, or why there is none. Only the cron passes `act`: it restarts a shard
	// that stopped early and stops one that finished, so reading /status changes nothing.
	async check(act = false): Promise<unknown> {
		const wanted = await this.ctx.storage.get<{ shard: number; shards: number }>('wanted');
		if (!wanted) return { state: 'idle' };
		const state = await this.getState();
		if (state.status !== 'running' && state.status !== 'healthy') {
			if (!act) return { state: 'not running', container: state.status };
			await this.launch();
			return { state: 'restarted', was: state.status };
		}
		const res = await this.containerFetch('http://container/status');
		const status = (await res.json()) as { state?: string };
		if (act && status.state === 'finished') {
			await this.ctx.storage.delete('wanted');
			await this.stop();
		}
		return status;
	}

	private async launch(): Promise<void> {
		const wanted = await this.ctx.storage.get<{ shard: number; shards: number }>('wanted');
		if (!wanted) return;
		const e = this.env;
		await this.startAndWaitForPorts({
			startOptions: {
				envVars: {
					SCRAPE_SHARD: `${wanted.shard}/${wanted.shards}`,
					SCRAPE_STORE: e.SCRAPE_STORE,
					SCRAPE_MAX_SOURCE_GB: e.SCRAPE_MAX_SOURCE_GB,
					R2_ACCOUNT_ID: e.R2_ACCOUNT_ID,
					R2_ACCESS_KEY_ID: e.R2_ACCESS_KEY_ID,
					R2_SECRET_ACCESS_KEY: e.R2_SECRET_ACCESS_KEY,
					MEGA_USERNAME: e.MEGA_USERNAME,
					MEGA_PASSWORD: e.MEGA_PASSWORD,
				},
			},
			// Cloning the catalog and reading the spreadsheet comes before the status port opens.
			cancellationOptions: { portReadyTimeoutMS: 300_000 },
		});
	}
}

function shards(env: Env): number[] {
	return [...Array(Number(env.SHARDS)).keys()];
}

function shard(env: Env, i: number) {
	return getContainer<Scraper>(env.SCRAPER, `shard-${i}`);
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const url = new URL(request.url);
		if (request.method === 'GET' && url.pathname === '/status') {
			const all = await Promise.all(shards(env).map(async (i) => ({ shard: i, ...((await shard(env, i).check()) as object) })));
			return Response.json(all);
		}
		if (request.method === 'POST' && (url.pathname === '/run' || url.pathname === '/stop')) {
			if (!env.RUN_TOKEN || request.headers.get('Authorization') !== `Bearer ${env.RUN_TOKEN}`) {
				return new Response('forbidden\n', { status: 403 });
			}
			const n = Number(env.SHARDS);
			await Promise.all(shards(env).map((i) => (url.pathname === '/run' ? shard(env, i).begin(i, n) : shard(env, i).end())));
			return Response.json({ ok: true, shards: n, action: url.pathname.slice(1) });
		}
		return new Response('GET /status, POST /run, POST /stop\n', { status: 404 });
	},

	async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
		ctx.waitUntil(Promise.all(shards(env).map((i) => shard(env, i).check(true))));
	},
};
