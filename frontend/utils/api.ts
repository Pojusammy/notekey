/**
 * API client — routes through Next.js API routes (same origin, no CORS).
 * In production, these routes can proxy to the FastAPI backend.
 */

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Request failed");
  }

  return res.json();
}

export const api = {
  /**
   * Upload a file.
   *
   * Strategy:
   *  1. Ask the backend for a Supabase presigned upload URL (/api/upload/init).
   *     The request body is tiny JSON — never hits Vercel's 4.5 MB limit.
   *  2. PUT the file directly to Supabase over HTTPS (large files, no proxy needed).
   *  3. Fallback: if the backend is in local-storage dev mode (useProxy:true) or
   *     the presigned-URL step fails, fall back to the /api/upload proxy (works
   *     for files under ~4 MB in dev).
   */
  async uploadFile(file: File, onProgress?: (pct: number) => void) {
    // ── Step 1: get presigned URL ──────────────────────────────────────────
    let presigned: { signedUrl: string; path: string; useProxy: boolean } | null = null;
    try {
      const res = await fetch("/api/upload/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name }),
      });
      if (res.ok) {
        presigned = await res.json();
      }
    } catch {
      // Backend unreachable — fall through to proxy
    }

    // ── Step 2: direct upload to Supabase (presigned URL) ──────────────────
    if (presigned && !presigned.useProxy && presigned.signedUrl) {
      return new Promise<{ fileUrl: string; fileId: string }>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("PUT", presigned!.signedUrl);
        xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");

        xhr.upload.addEventListener("progress", (e) => {
          if (e.lengthComputable && onProgress) {
            onProgress(Math.round((e.loaded / e.total) * 100));
          }
        });

        xhr.addEventListener("load", () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve({ fileUrl: presigned!.path, fileId: presigned!.path });
          } else {
            reject(new Error("Upload failed"));
          }
        });

        xhr.addEventListener("error", () =>
          reject(new Error("Network error — could not reach server"))
        );
        xhr.send(file);
      });
    }

    // ── Step 3: proxy fallback (/api/upload) ──────────────────────────────
    const formData = new FormData();
    formData.append("file", file);

    return new Promise<{ fileUrl: string; fileId: string }>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");

      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      });

      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText));
        } else {
          let detail = "Upload failed";
          try {
            const body = JSON.parse(xhr.responseText);
            detail = body.detail || body.error || detail;
          } catch {}
          reject(new Error(detail));
        }
      });

      xhr.addEventListener("error", () =>
        reject(new Error("Network error — could not reach server"))
      );
      xhr.send(formData);
    });
  },

  // Analysis
  async startAnalysis(params: {
    fileUrl: string;
    selectedKey: string;
    startTime?: string;
    endTime?: string;
    songKey?: string;
    startingNote?: string;
    analysisMode?: string;
  }) {
    return request<{ jobId: string }>("/api/analyze", {
      method: "POST",
      body: JSON.stringify(params),
    });
  },

  async getJobStatus(jobId: string) {
    return request<{
      id: string;
      status: string;
      completedAt?: string;
      errorMessage?: string;
    }>(`/api/jobs/${jobId}`);
  },

  async getResult(resultId: string) {
    return request<{
      id: string;
      noteSequence: Array<{
        noteName: string;
        octave: number;
        startTime: number;
        duration: number;
        frequency: number;
        solfa: string;
      }>;
      solfaSequence: string[];
      confidenceScore: number;
    }>(`/api/results/${resultId}`);
  },

  // History
  async getHistory() {
    return request<
      Array<{
        id: string;
        title: string;
        resultId: string;
        createdAt: string;
      }>
    >("/api/history");
  },

  async deleteSession(id: string) {
    return request(`/api/history/${id}`, { method: "DELETE" });
  },
};
