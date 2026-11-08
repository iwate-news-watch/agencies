/**
 * 岩手県 市町村新着情報 — 更新ボタン用の中継サーバー（Cloudflare Workers）
 *
 * このファイルをそのまま Cloudflare のダッシュボードの Worker エディタに貼り付けて使います。
 *
 *   POST /trigger  … GitHub Actions のワークフローを手動実行（workflow_dispatch, main）
 *   GET  /status   … 最新の実行の時刻と状態
 *
 * 設定（Worker の「設定 → 変数とシークレット」）
 *   GITHUB_OWNER    例: nowakinowaki
 *   GITHUB_REPO     例: test
 *   WORKFLOW_FILE   例: daily.yml
 *   ALLOWED_ORIGIN  公開ページのオリジン 例: https://nowakinowaki.github.io（末尾の / やパスは付けない）
 *   GITHUB_TOKEN    ※「シークレット」として登録。fine-grained トークン（Actions: Read and write）
 */

const COOLDOWN_MS = 15 * 60 * 1000; // 前回の実行開始からこの時間は受け付けない
const BUSY_RETRY_MS = 5 * 60 * 1000; // 実行中・待機中のとき、次に試せる時刻の目安
const ACTIVE = new Set(["queued", "in_progress", "waiting", "requested", "pending"]);

// 同じ Worker インスタンス内での連打対策（GitHub に実行が現れるまでの数秒間をふさぐ）
let lastTriggeredAt = 0;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin");
    const cors = corsHeaders(origin, env);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: cors ? 204 : 403, headers: cors || {} });
    }
    // ブラウザからの呼び出しは公開ページのオリジンだけ許可
    if (origin && !cors) {
      return json({ error: "origin_not_allowed" }, 403);
    }

    try {
      if (url.pathname === "/status" && request.method === "GET") {
        return json(await getStatus(env), 200, cors);
      }
      if (url.pathname === "/trigger" && request.method === "POST") {
        if (!cors) return json({ error: "origin_not_allowed" }, 403);
        return await trigger(env, cors);
      }
      return json({ error: "not_found" }, 404, cors);
    } catch (e) {
      return json({ error: "upstream_error", message: String(e.message || e) }, 502, cors);
    }
  },
};

async function trigger(env, cors) {
  const status = await getStatus(env);
  const now = Date.now();
  const recent = now - lastTriggeredAt < COOLDOWN_MS;
  if (!status.canTrigger || recent) {
    let next = status.nextAvailableAt;
    if (recent) {
      const local = new Date(lastTriggeredAt + COOLDOWN_MS).toISOString();
      if (!next || local > next) next = local;
    }
    return json(
      { accepted: false, reason: status.busy ? "busy" : "cooldown", nextAvailableAt: next, latest: status.latest },
      429,
      cors,
    );
  }

  lastTriggeredAt = now;
  const res = await github(env, `/actions/workflows/${encodeURIComponent(env.WORKFLOW_FILE)}/dispatches`, {
    method: "POST",
    body: JSON.stringify({ ref: "main" }),
  });
  if (res.status !== 204) {
    lastTriggeredAt = 0;
    throw new Error(`workflow_dispatch failed: ${res.status} ${await res.text()}`);
  }
  return json(
    { accepted: true, nextAvailableAt: new Date(now + COOLDOWN_MS).toISOString() },
    202,
    cors,
  );
}

async function getStatus(env) {
  const res = await github(
    env,
    `/actions/workflows/${encodeURIComponent(env.WORKFLOW_FILE)}/runs?per_page=5&branch=main`,
  );
  if (!res.ok) throw new Error(`list runs failed: ${res.status} ${await res.text()}`);
  const runs = (await res.json()).workflow_runs || [];
  const now = Date.now();

  const latestRun = runs[0];
  const latest = latestRun
    ? {
        status: latestRun.status, // queued / in_progress / completed など
        conclusion: latestRun.conclusion, // success / failure / null
        event: latestRun.event, // schedule / workflow_dispatch
        createdAt: latestRun.created_at,
        startedAt: latestRun.run_started_at || latestRun.created_at,
        updatedAt: latestRun.updated_at,
      }
    : null;

  const busy = runs.some((r) => ACTIVE.has(r.status));
  let next = null;
  if (latest) {
    const cooldownEnd = Date.parse(latest.startedAt) + COOLDOWN_MS;
    if (cooldownEnd > now) next = cooldownEnd;
  }
  if (busy) next = Math.max(next || 0, now + BUSY_RETRY_MS);

  return {
    latest,
    busy,
    canTrigger: next === null,
    nextAvailableAt: next === null ? null : new Date(next).toISOString(),
  };
}

function github(env, path, init = {}) {
  return fetch(`https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "iwate-news-trigger",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
}

function corsHeaders(origin, env) {
  const allowed = (env.ALLOWED_ORIGIN || "").replace(/\/+$/, "");
  if (!origin || !allowed || origin !== allowed) return null;
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...(extraHeaders || {}) },
  });
}
