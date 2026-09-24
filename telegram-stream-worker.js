// ═══════════════════════════════════════════════════════════
// Telegram Video Streaming Proxy — Cloudflare Worker
// يدعم البث المباشر مع Range Requests (206 Partial Content)
// ═══════════════════════════════════════════════════════════

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "Range",
  "Access-Control-Expose-Headers":
    "Content-Length, Content-Range, Accept-Ranges",
};

export default {
  async fetch(request, env) {
    // ─── OPTIONS ───
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS });
    }

    const url = new URL(request.url);

    // ─── Health Check ───
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response("Telegram Stream Worker OK", {
        status: 200,
        headers: { ...CORS, "Content-Type": "text/plain" },
      });
    }

    // ─── Stream Endpoint ───
    if (url.pathname !== "/stream") {
      return new Response("Not Found", { status: 404, headers: CORS });
    }

    const fileId = url.searchParams.get("fid");
    if (!fileId) {
      return new Response("Missing fid parameter", { status: 400, headers: CORS });
    }

    const BOT_TOKEN = env.BOT_TOKEN;
    if (!BOT_TOKEN) {
      return new Response("Missing BOT_TOKEN", { status: 500, headers: CORS });
    }

    try {
      // ─── 1) الحصول على مسار الملف ───
      const fileRes = await fetch(
        `https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${encodeURIComponent(fileId)}`
      );
      const fileData = await fileRes.json();

      if (!fileData.ok) {
        const errMsg = fileData.description || "Unknown error";
        // ─── إذا كان الملف > 20MB ───
        if (errMsg.includes("too big") || errMsg.includes("file is too big")) {
          return new Response(
            JSON.stringify({
              error: "FILE_TOO_LARGE",
              message: "الملف يتجاوز 20MB — استخدم البث عبر MTProto Proxy",
            }),
            { status: 413, headers: { ...CORS, "Content-Type": "application/json" } }
          );
        }
        return new Response("getFile failed: " + errMsg, { status: 500, headers: CORS });
      }

      const filePath = fileData.result.file_path;
      const fileSize = fileData.result.file_size;
      const fileUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${filePath}`;

      // ─── 2) تمرير Range Header ───
      const rangeHeader = request.headers.get("Range");
      const upstreamHeaders = {};
      if (rangeHeader) upstreamHeaders["Range"] = rangeHeader;

      const upstream = await fetch(fileUrl, { headers: upstreamHeaders });

      // ─── 3) تجهيز الترويسات ───
      const respHeaders = new Headers(CORS);
      respHeaders.set(
        "Content-Type",
        upstream.headers.get("Content-Type") || "video/mp4"
      );
      respHeaders.set("Accept-Ranges", "bytes");

      const cl = upstream.headers.get("Content-Length") || fileSize;
      if (cl) respHeaders.set("Content-Length", cl);

      const cr = upstream.headers.get("Content-Range");
      if (cr) respHeaders.set("Content-Range", cr);

      respHeaders.set("Cache-Control", "public, max-age=86400");

      return new Response(upstream.body, {
        status: upstream.status,
        headers: respHeaders,
      });
    } catch (e) {
      return new Response("Error: " + e.message, { status: 500, headers: CORS });
    }
  },
};
