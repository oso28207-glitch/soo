// ═══════════════════════════════════════════════════════════
//  Telegram Video Streaming Proxy — Cloudflare Worker
//  الاستخدام: /stream?fid=<file_id>
// ═══════════════════════════════════════════════════════════

export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
      "Access-Control-Allow-Headers": "Range",
      "Access-Control-Expose-Headers":
        "Content-Length, Content-Range, Accept-Ranges",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: cors });
    }

    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response("Telegram Stream Worker OK", {
        status: 200,
        headers: cors,
      });
    }

    if (url.pathname !== "/stream") {
      return new Response("Not Found", { status: 404, headers: cors });
    }

    const fileId = url.searchParams.get("fid");
    if (!fileId) {
      return new Response("Missing fid", { status: 400, headers: cors });
    }

    const BOT_TOKEN = env.BOT_TOKEN;
    if (!BOT_TOKEN) {
      return new Response("Missing BOT_TOKEN", { status: 500, headers: cors });
    }

    try {
      // 1) احصل على مسار الملف
      const fileRes = await fetch(
        `https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${encodeURIComponent(fileId)}`
      );
      const fileData = await fileRes.json();
      if (!fileData.ok) {
        return new Response(
          "getFile failed: " + JSON.stringify(fileData),
          { status: 500, headers: cors }
        );
      }

      const filePath = fileData.result.file_path;
      const fileSize = fileData.result.file_size;
      const fileUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${filePath}`;

      // 2) مرّر Range
      const rangeHeader = request.headers.get("Range");
      const upstreamHeaders = {};
      if (rangeHeader) upstreamHeaders["Range"] = rangeHeader;

      const upstream = await fetch(fileUrl, { headers: upstreamHeaders });

      // 3) جهّز الترويسات
      const respHeaders = new Headers(cors);
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
      return new Response("Error: " + e.message, {
        status: 500,
        headers: cors,
      });
    }
  },
};
