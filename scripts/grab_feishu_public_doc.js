#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    const value = argv[i + 1];
    if (!key.startsWith("--")) continue;
    if (key === "--write-meta") {
      out.writeMeta = true;
      continue;
    }
    out[key.slice(2)] = value;
  }
  return out;
}

const args = parseArgs(process.argv);
const required = [
  "url",
  "page-id",
  "space-id",
  "container-id",
  "title",
  "dest-dir",
  "cookie-header",
];
for (const key of required) {
  if (!args[key]) {
    throw new Error(`Missing required argument --${key}`);
  }
}

const PAGE_ID = args["page-id"];
const SPACE_ID = args["space-id"];
const CONTAINER_ID = args["container-id"];
const SOURCE_URL = args.url;
const DISPLAY_SOURCE_URL = args["display-source-url"] || SOURCE_URL;
const COOKIE_HEADER = args["cookie-header"];
const DEST_DIR = args["dest-dir"];
const NOTE_DATE = args.date || new Date().toISOString().slice(0, 10).replace(/-/g, "");
const NOW = new Date();
const REQUEST_TIMEOUT_MS = 30000;
const DEBUG_MODE = process.env.FEISHU_DEBUG === "1";

function debug(...parts) {
  if (!DEBUG_MODE) return;
  console.error("[feishu-debug]", ...parts);
}

function dumpActiveHandles(tag) {
  if (!DEBUG_MODE) return;
  const handles = typeof process._getActiveHandles === "function" ? process._getActiveHandles() : [];
  const requests = typeof process._getActiveRequests === "function" ? process._getActiveRequests() : [];
  console.error(
    "[feishu-debug]",
    tag,
    JSON.stringify(
      {
        handle_types: handles.map((h) => h?.constructor?.name || typeof h),
        request_types: requests.map((r) => r?.constructor?.name || typeof r),
      },
      null,
      2
    )
  );
}

function sanitizeTitle(input) {
  return input
    .replace(/^[^\p{Script=Han}\p{L}\p{N}]+/u, "")
    .replace(/[^\p{Script=Han}\p{L}\p{N}]+$/u, "")
    .replace(/[\/\\:*?"<>|]/g, "")
    .replace(/\s+/g, " ")
    .replace(/[。.\s]+$/g, "")
    .trim()
    .slice(0, 80);
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function localTimeBase(d) {
  return (
    d.getFullYear() +
    pad2(d.getMonth() + 1) +
    pad2(d.getDate()) +
    pad2(d.getHours()) +
    pad2(d.getMinutes()) +
    pad2(d.getSeconds())
  );
}

const TITLE = sanitizeTitle(args.title);
const NOTE_BASENAME = `${NOTE_DATE}--${TITLE}__note`;
const NOTE_PATH = path.join(DEST_DIR, `${NOTE_BASENAME}.md`);
const ASSET_DIR = path.join(DEST_DIR, "assets", NOTE_BASENAME);
const META_PATH = path.join(DEST_DIR, `${NOTE_BASENAME}.meta.json`);
const BASE_URL =
  "https://waytoagi.feishu.cn/space/api/docx/pages/client_vars" +
  `?id=${PAGE_ID}&mode=7&limit=239&wiki_space_id=${SPACE_ID}` +
  `&container_type=wiki2.0&container_id=${CONTAINER_ID}`;

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function resetDir(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
}

async function fetchJson(url, init = {}) {
  const res = await fetch(url, {
    ...init,
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    headers: {
      accept: "application/json, text/plain, */*",
      cookie: COOKIE_HEADER,
      "user-agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
      ...init.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} for ${url}`);
  }
  return res.json();
}

function textFromBlock(block) {
  const texts = block?.data?.text?.initialAttributedTexts?.text;
  if (!texts || typeof texts !== "object") return "";
  return Object.keys(texts)
    .sort((a, b) => Number(a) - Number(b))
    .map((k) => texts[k] || "")
    .join("")
    .replace(/\u000b/g, "\n")
    .trim();
}

function textFromBlockId(blocks, id, seen = new Set()) {
  if (!id || seen.has(id)) return "";
  seen.add(id);
  const block = blocks[id];
  if (!block?.data) return "";
  const direct = textFromBlock(block);
  const childTexts = (block.data.children || [])
    .map((childId) => textFromBlockId(blocks, childId, seen))
    .filter(Boolean);
  return [direct, ...childTexts].filter(Boolean).join("\n").trim();
}

function escapeTableCell(text) {
  return (text || "")
    .replace(/\n+/g, "<br>")
    .replace(/\|/g, "\\|")
    .trim();
}

function renderTable(blocks, block) {
  const rows = block?.data?.rows_id || [];
  const columns = Object.keys(block?.data?.column_set || {});
  const cellSet = block?.data?.cell_set || {};
  if (!rows.length || !columns.length) {
    return ["> 表格块（空表或结构不完整）", ""];
  }

  const matrix = rows.map((rowId) =>
    columns.map((colId) => {
      const cell = cellSet[`${rowId}${colId}`];
      const value = cell?.block_id ? textFromBlockId(blocks, cell.block_id) : "";
      return escapeTableCell(value);
    })
  );

  const header = matrix[0];
  const body = matrix.slice(1);
  const separator = header.map(() => "---");
  const lines = [
    `| ${header.join(" | ")} |`,
    `| ${separator.join(" | ")} |`,
  ];
  for (const row of body) {
    lines.push(`| ${row.join(" | ")} |`);
  }
  lines.push("");
  return lines;
}

async function loadAllBlocks() {
  const blocks = {};
  let cursor = null;
  const seenCursors = new Set();
  for (let i = 0; i < 20; i += 1) {
    debug("loadAllBlocks.page", i + 1, cursor ? "cursor" : "root");
    const url = cursor ? `${BASE_URL}&cursor=${encodeURIComponent(cursor)}` : BASE_URL;
    const json = await fetchJson(url);
    Object.assign(blocks, json.data?.block_map || {});
    debug(
      "loadAllBlocks.result",
      "has_more=",
      Boolean(json.data?.has_more),
      "next_cursors=",
      json.data?.next_cursors?.length || 0,
      "cursor=",
      json.data?.cursor ? "present" : "missing",
      "block_count=",
      Object.keys(blocks).length
    );
    if (!json.data?.has_more) break;
    const nextCursor = json.data?.next_cursors?.[0] || json.data?.cursor || null;
    if (!nextCursor || seenCursors.has(nextCursor)) break;
    seenCursors.add(nextCursor);
    cursor = nextCursor;
  }
  return blocks;
}

function renderBlocks(blocks) {
  const root = blocks[PAGE_ID];
  if (!root) throw new Error("Root page block not found");

  const lines = [`# ${TITLE}`, "", `原文链接: ${DISPLAY_SOURCE_URL}`, ""];
  const imagePlan = [];
  const visited = new Set();

  const render = (id, depth = 0) => {
    if (!id || visited.has(id)) return;
    visited.add(id);
    const block = blocks[id];
    if (!block?.data) return;
    const data = block.data;
    const type = data.type;
    const text = textFromBlock(block);

    if (type === "page" || type === "grid" || type === "grid_column" || type === "view") {
      for (const childId of data.children || []) render(childId, depth + 1);
      return;
    }

    if (type === "heading1" || type === "heading2" || type === "heading3" || type === "heading4") {
      const level = Number(type.slice(-1));
      lines.push(`${"#".repeat(level)} ${text || "(空标题)"}`, "");
    } else if (type === "bullet") {
      lines.push(`${"  ".repeat(Math.max(depth - 1, 0))}- ${text}`);
    } else if (type === "ordered") {
      lines.push(`${"  ".repeat(Math.max(depth - 1, 0))}1. ${text}`);
    } else if (type === "quote") {
      if (text) {
        for (const line of text.split("\n")) lines.push(`> ${line}`);
        lines.push("");
      }
      return;
    } else if (type === "table") {
      lines.push(...renderTable(blocks, block));
      return;
    } else if (type === "code") {
      const language = data.code?.language || "";
      const codeText = text || textFromBlockId(blocks, id);
      lines.push(`\`\`\`${language}`, codeText, "```", "");
      return;
    } else if (type === "callout") {
      if (text) lines.push(`> ${text}`);
      for (const childId of data.children || []) render(childId, depth + 1);
      lines.push("");
      return;
    } else if (type === "image") {
      imagePlan.push({
        token: data.image?.token || "",
        name: data.image?.name || "",
        width: data.image?.width || 1280,
        height: data.image?.height || 1280,
        caption:
          textFromBlock({ data: { text: data.image?.caption?.text } }) ||
          data.image?.name ||
          `image ${imagePlan.length + 1}`,
      });
      lines.push(`__IMAGE_${imagePlan.length - 1}__`, "");
    } else if (type === "file") {
      const name = data.file?.name || text || "未命名附件";
      const token = data.file?.token || data.token || "";
      lines.push(`> 附件块: ${name} token=\`${token}\``, "");
    } else if (type === "sheet") {
      lines.push(`> 嵌入表格: token=\`${data.token || ""}\``, "");
    } else if (type === "synced_reference") {
      lines.push(`> 同步引用: src_page_id=\`${data.src_page_id}\`, src_block_id=\`${data.src_block_id}\``, "");
    } else if (type === "isv") {
      lines.push(`> 插件块: block_type_id=\`${data.block_type_id || ""}\``, "");
    } else if (text) {
      lines.push(text, "");
    }

    for (const childId of data.children || []) render(childId, depth + 1);
  };

  for (const childId of root.data.children || []) render(childId, 0);

  const compact = [];
  for (const line of lines) {
    if (line === "" && compact[compact.length - 1] === "") continue;
    compact.push(line);
  }
  compact.push("");
  return { markdown: compact.join("\n"), imagePlan };
}

async function resolveImageAssets(imagePlan) {
  const resolved = new Map();
  for (let i = 0; i < imagePlan.length; i += 15) {
    debug("resolveImageAssets.batch", i, i + 15, "total", imagePlan.length);
    const batch = imagePlan.slice(i, i + 15);
    const body = batch.map((img) => ({
      file_token: img.token,
      policy: "near",
      width: img.width,
      height: img.height,
    }));
    const json = await fetchJson("https://waytoagi.feishu.cn/space/api/box/file/cdn_url/", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    for (const item of json.data || []) {
      if (item?.file_token && item?.url) resolved.set(item.file_token, item);
    }
  }
  return resolved;
}

async function downloadBuffer(url) {
  const res = await fetch(url, {
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    headers: {
      "user-agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    },
  });
  if (!res.ok) throw new Error(`Download failed ${res.status} for ${url}`);
  return Buffer.from(await res.arrayBuffer());
}

function decryptFeishuBuffer(buf, secret, nonce, cipherType) {
  if (cipherType !== "1" || !secret || !nonce) return buf;
  const key = Buffer.from(secret, "base64");
  const iv = Buffer.from(nonce, "base64");
  const tag = buf.subarray(buf.length - 16);
  const data = buf.subarray(0, buf.length - 16);
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(data), decipher.final()]);
}

function detectExt(buf) {
  if (buf.length >= 8 && buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "png";
  if (buf.length >= 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return "jpeg";
  if (buf.length >= 6 && ["GIF87a", "GIF89a"].includes(buf.subarray(0, 6).toString("ascii"))) return "gif";
  if (buf.length >= 12 && buf.subarray(0, 4).toString("ascii") === "RIFF" && buf.subarray(8, 12).toString("ascii") === "WEBP") return "webp";
  return "bin";
}

function stampForIndex(index) {
  const base = localTimeBase(NOW);
  return `${base}${String(index + 1).padStart(3, "0")}`;
}

async function main() {
  let debugTimer = null;
  if (DEBUG_MODE) {
    debugTimer = setTimeout(() => dumpActiveHandles("timeout-dump"), 15000);
  }
  resetDir(ASSET_DIR);
  debug("main.start", SOURCE_URL);
  const blocks = await loadAllBlocks();
  debug("main.blocks_loaded", Object.keys(blocks).length);
  let { markdown, imagePlan } = renderBlocks(blocks);
  debug("main.rendered", "markdown_chars=", markdown.length, "images=", imagePlan.length);
  const assets = await resolveImageAssets(imagePlan);
  debug("main.assets_resolved", assets.size);

  imagePlan = imagePlan.map((img, index) => {
    const asset = assets.get(img.token);
    if (!asset?.url) throw new Error(`Missing asset URL for token ${img.token}`);
    return { ...img, asset, index };
  });

  for (const img of imagePlan) {
    const raw = await downloadBuffer(img.asset.url);
    const dec = decryptFeishuBuffer(raw, img.asset.secret, img.asset.nonce, img.asset.cipher_type);
    const ext = detectExt(dec);
    const fileName = `file-${stampForIndex(img.index)}.${ext}`;
    fs.writeFileSync(path.join(ASSET_DIR, fileName), dec);
    const wikiLink = `![[assets/${NOTE_BASENAME}/${fileName}]]`;
    markdown = markdown.replace(`__IMAGE_${img.index}__`, wikiLink);
    img.fileName = fileName;
  }

  ensureDir(DEST_DIR);
  fs.writeFileSync(NOTE_PATH, markdown, "utf8");
  debug("main.note_written", NOTE_PATH);

  if (args.writeMeta) {
    const meta = {
      source_url: SOURCE_URL,
      fetched_at: new Date().toISOString(),
      title: TITLE,
      page_id: PAGE_ID,
      space_id: SPACE_ID,
      container_id: CONTAINER_ID,
      public_page: true,
      note_path: NOTE_PATH,
      asset_dir: ASSET_DIR,
      asset_count: imagePlan.length,
    };
    fs.writeFileSync(META_PATH, JSON.stringify(meta, null, 2), "utf8");
    debug("main.meta_written", META_PATH);
  }

  console.log(
    JSON.stringify(
      {
        note_path: NOTE_PATH,
        asset_dir: ASSET_DIR,
        asset_count: imagePlan.length,
        meta_path: args.writeMeta ? META_PATH : null,
      },
      null,
      2
    )
  );
  if (debugTimer) clearTimeout(debugTimer);
  dumpActiveHandles("before-return");
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
