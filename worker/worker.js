/**
 * GINGA 岩手県 国の機関・大学 新着情報 — 更新ボタン用の中継サーバー（Cloudflare Workers）
 *
 * このファイルをそのまま Cloudflare のダッシュボードの Worker エディタに貼り付けて使います。
 *
 *   POST /trigger  … GitHub Actions のワークフローを手動実行（workflow_dispatch, main）
 *   GET  /status   … 最新の実行の時刻と状態
 *   GET  /proxy?url=… … 許可したサイト（既定は www.iwate-pu.ac.jp だけ）のページを代わりに取得して返す
 *                    （GitHub Actions から直接取得できないサイト用。結果は数分キャッシュする）
 *
 * 設定（Worker の「設定 → 変数とシークレット」）
 *   GITHUB_OWNER    例: iwate-news-watch
 *   GITHUB_REPO     例: agencies
 *   WORKFLOW_FILE   例: daily.yml
 *   ALLOWED_ORIGIN  公開ページのオリジン 例: https://iwate-news-watch.github.io（末尾の / やパスは付けない）
 *   GITHUB_TOKEN    ※「シークレット」として登録。fine-grained トークン（Actions: Read and write）
 *   PROXY_ALLOWED_HOSTS （任意）/proxy で取得してよいホスト名。カンマ区切り。省略時は www.iwate-pu.ac.jp だけ
 */

const COOLDOWN_MS = 15 * 60 * 1000; // 前回の実行開始からこの時間は受け付けない
const BUSY_RETRY_MS = 5 * 60 * 1000; // 実行中・待機中のとき、次に試せる時刻の目安
const ACTIVE = new Set(["queued", "in_progress", "waiting", "requested", "pending"]);

// /proxy の設定
const PROXY_DEFAULT_HOSTS = ["www.iwate-pu.ac.jp"];
const PROXY_CACHE_SECONDS = 300; // 同じURLはこの時間キャッシュを返し、相手のサイトに何度もアクセスしない
const PROXY_MAX_REDIRECTS = 5;
const PROXY_MAX_BYTES = 5 * 1024 * 1024;
const PROXY_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  "Accept-Language": "ja",
  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
};

// 同じ Worker インスタンス内での連打対策（GitHub に実行が現れるまでの数秒間をふさぐ）
let lastTriggeredAt = 0;

export default {
  async fetch(request, env, ctx) {
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
      if (url.pathname === "/proxy" && request.method === "GET") {
        return await proxy(url, env, ctx);
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

// ---------------------------------------------------------------------------
// /proxy … 許可したホストのページだけを取得する（踏み台に使われないよう、それ以外は拒否）
// ---------------------------------------------------------------------------

function allowedHosts(env) {
  const list = String(env.PROXY_ALLOWED_HOSTS || "")
    .split(",")
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean);
  return list.length ? list : PROXY_DEFAULT_HOSTS;
}

// 取得してよいURLか（http/https・許可したホスト・既定のポート・ユーザー情報なし）
function checkTarget(raw, env) {
  let t;
  try {
    t = new URL(raw);
  } catch {
    return null;
  }
  if (t.protocol !== "https:" && t.protocol !== "http:") return null;
  if (t.username || t.password || t.port) return null;
  if (!allowedHosts(env).includes(t.hostname.toLowerCase())) return null;
  t.hash = "";
  return t;
}

async function proxy(url, env, ctx) {
  const target = checkTarget(url.searchParams.get("url") || "", env);
  if (!target) return json({ error: "url_not_allowed", allowed: allowedHosts(env) }, 403);

  // キャッシュの鍵は「正規化した取得先URL」。同じページへの短時間の連続アクセスはキャッシュで返す
  const cacheKey = new Request(`https://proxy-cache.invalid/${encodeURIComponent(target.href)}`);
  const cache = caches.default;
  const hit = await cache.match(cacheKey);
  if (hit) {
    const res = new Response(hit.body, hit);
    res.headers.set("X-Proxy-Cache", "HIT");
    return res;
  }

  // リダイレクトは自分でたどり、転送先も許可したホストかを毎回確かめる
  let current = target;
  let upstream;
  for (let i = 0; ; i++) {
    upstream = await fetch(current.href, { headers: PROXY_HEADERS, redirect: "manual" });
    const loc = upstream.headers.get("Location");
    if (upstream.status >= 300 && upstream.status < 400 && loc) {
      if (i >= PROXY_MAX_REDIRECTS) return json({ error: "too_many_redirects" }, 502);
      const next = checkTarget(new URL(loc, current).href, env);
      if (!next) return json({ error: "redirect_not_allowed", location: loc }, 502);
      current = next;
      continue;
    }
    break;
  }

  const body = await upstream.arrayBuffer();
  if (body.byteLength > PROXY_MAX_BYTES) return json({ error: "too_large" }, 502);
  const headers = {
    "Content-Type": upstream.headers.get("Content-Type") || "application/octet-stream",
    "Cache-Control": `public, max-age=${PROXY_CACHE_SECONDS}`,
    "X-Proxy-Final-Url": current.href,
    "X-Proxy-Upstream-Status": String(upstream.status),
    "X-Proxy-Upstream-Server": upstream.headers.get("Server") || "",
    "X-Proxy-Cache": "MISS",
  };
  const res = new Response(body, { status: upstream.status, headers });
  if (upstream.status === 200) {
    ctx.waitUntil(cache.put(cacheKey, res.clone()));
  }
  return res;
}

// ---------------------------------------------------------------------------
// /trigger・/status
// ---------------------------------------------------------------------------

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
