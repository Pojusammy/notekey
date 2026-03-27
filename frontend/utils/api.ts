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
  // Upload — uses XHR for progress tracking
  async uploadFile(file: File, onProgress?: (pct: number) => void) {
    const formData = new FormData();
    formData.append("file", file);

    return new Promise<{ fileUrl: string; fileId: string }>(
      (resolve, reject) => {
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
              detail = JSON.parse(xhr.responseText).detail || detail;
            } catch {}
            reject(new Error(detail));
          }
        });

        xhr.addEventListener("error", () =>
          reject(new Error("Network error — could not reach server"))
        );
        xhr.send(formData);
      }
    );
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
