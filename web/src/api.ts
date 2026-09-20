import type { Alert, PharmacyJob, ScanResult, ShelfItem, Stats } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

/**
 * A per-device identifier for the shelf.
 *
 * This is a namespace, not a security boundary. When the API is deployed with
 * RequireLogin=true it is ignored and identity comes from the Cognito JWT
 * instead; a token stored under `bw.token` is sent whenever it exists.
 */
function deviceId(): string {
  const KEY = "bw.device";
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(KEY, id);
  }
  return id;
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const out: Record<string, string> = {
    "content-type": "application/json",
    "x-device-id": deviceId(),
    ...extra,
  };
  const token = localStorage.getItem("bw.token");
  if (token) out["authorization"] = `Bearer ${token}`;
  return out;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers: headers(init.headers as never) });
  } catch {
    throw new ApiError(0, "Could not reach the server. Is it running?");
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    throw new ApiError(res.status, text.slice(0, 200) || "The server sent something unreadable.");
  }
  if (!res.ok) {
    const message =
      (body as { error?: string })?.error ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, message);
  }
  return body as T;
}

export const api = {
  stats: () => request<Stats>("/stats"),

  scanText: (text: string) =>
    request<ScanResult>("/scan", { method: "POST", body: JSON.stringify({ text }) }),

  scanImage: (image: string, mediaType: string, fallbackText = "") =>
    request<ScanResult>("/scan", {
      method: "POST",
      body: JSON.stringify({ image, media_type: mediaType, text: fallbackText }),
    }),

  shelf: () => request<{ items: ShelfItem[]; count: number }>("/shelf"),

  addToShelf: (item: Record<string, unknown>) =>
    request<{ item: ShelfItem; verdict: ScanResult }>("/shelf", {
      method: "POST",
      body: JSON.stringify(item),
    }),

  removeFromShelf: (id: string) =>
    request<{ deleted: string }>(`/shelf/${encodeURIComponent(id)}`, { method: "DELETE" }),

  alerts: (markRead = false) =>
    request<{ alerts: Alert[]; count: number; unread: number }>(
      `/alerts${markRead ? "?mark_read=1" : ""}`,
    ),

  search: (q: string) =>
    request<{ query: string; mode: string; count: number; results: import("./types").NsqRow[]; note: string }>(
      `/search?q=${encodeURIComponent(q)}`,
    ),

  pharmacyCheck: (csv: string) =>
    request<PharmacyJob>("/pharmacy/check", { method: "POST", body: JSON.stringify({ csv }) }),
};

/**
 * Downscale before upload.
 *
 * A modern phone camera produces 4-12MB per frame; the batch code is legible
 * at 1400px on the long edge. This cuts upload time and the per-scan vision
 * cost by roughly an order of magnitude, and it happens before the image
 * leaves the device.
 */
export async function downscale(file: File, maxEdge = 1400, quality = 0.8): Promise<{
  data: string;
  mediaType: string;
  originalKB: number;
  sentKB: number;
}> {
  const originalKB = Math.round(file.size / 1024);
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser cannot resize the image.");
  ctx.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();

  const dataUrl = canvas.toDataURL("image/jpeg", quality);
  const data = dataUrl.split(",", 2)[1] ?? "";
  return {
    data,
    mediaType: "image/jpeg",
    originalKB,
    sentKB: Math.round((data.length * 3) / 4 / 1024),
  };
}
