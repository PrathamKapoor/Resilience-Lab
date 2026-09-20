export class ApiError extends Error {
  constructor(status, detail) {
    super(`Request failed (${status}): ${detail}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function request(path) {
  const localApiKey = import.meta.env.MODE === 'production'
    ? undefined
    : import.meta.env.VITE_RESILIENCELAB_API_KEY;
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...(localApiKey ? { headers: { 'X-API-Key': localApiKey } } : {}),
  });
  const text = await response.text();

  if (!response.ok) {
    let detail = text || response.statusText || 'Unknown error';
    try {
      detail = JSON.parse(text).detail || detail;
    } catch {
      // Non-JSON error responses remain readable as text.
    }
    throw new ApiError(response.status, detail);
  }

  return text;
}

export async function getJson(path) {
  const text = await request(path);
  return text ? JSON.parse(text) : null;
}

export function getText(path) {
  return request(path);
}
