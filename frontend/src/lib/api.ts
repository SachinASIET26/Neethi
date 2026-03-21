import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from "axios";
import Cookies from "js-cookie";
import type {
  RegisterRequest, RegisterResponse, LoginRequest, TokenResponse,
  RefreshResponse, UserProfile, QueryRequest, QueryResponse,
  QueryHistoryResponse, FeedbackRequest, CaseSearchRequest, CaseSearchResponse,
  CaseAnalysisRequest, CaseAnalysisResponse, CaseDetail,
  SimilarCasesRequest, SimilarCasesResponse, TemplateListResponse,
  DraftRequest, DraftResponse, DraftUpdateRequest, ActListResponse, SectionDetail,
  NormalizeResponse, VerifyRequest, VerifyResponse, NearbyRequest, NearbyResponse,
  TranslateTextRequest, TranslateTextResponse,
  TranslateQueryRequest, TranslateQueryResponse, HealthResponse,
  UserListResponse, UserDetailResponse, UserUpdateRequest, AdminStats, ActivityResponse,
  TurnRequest, TurnResponse, SessionResponse, DocumentAnalysisResponse,
} from "@/types";

// Always use relative path — Next.js proxies /api/v1/* → backend (localhost:8000 or BACKEND_URL).
// This works on Lightning AI, local dev, and production without any env var changes.
const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "/api/v1";

// ===================== AXIOS INSTANCE =====================

const apiClient: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 60000,
});

// Request interceptor — attach token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = Cookies.get("neethi_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor — auto-refresh token
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        const token = Cookies.get("neethi_token");
        if (token) {
          const { data } = await axios.post<RefreshResponse>(
            `${BASE_URL}/auth/refresh`,
            {},
            { headers: { Authorization: `Bearer ${token}` } }
          );
          Cookies.set("neethi_token", data.access_token, { expires: 1, secure: true, sameSite: "strict" });
          originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
          return apiClient(originalRequest);
        }
      } catch {
        Cookies.remove("neethi_token");
        Cookies.remove("neethi_user");
        window.location.href = "/login";
      }
    }

    return Promise.reject(error);
  }
);

// ===================== AUTH =====================

export const authAPI = {
  register: (data: RegisterRequest) =>
    apiClient.post<RegisterResponse>("/auth/register", data).then(r => r.data),

  login: (data: LoginRequest) =>
    apiClient.post<TokenResponse>("/auth/login", data).then(r => r.data),

  logout: () =>
    apiClient.post("/auth/logout").then(r => r.data),

  refresh: () =>
    apiClient.post<RefreshResponse>("/auth/refresh").then(r => r.data),

  me: () =>
    apiClient.get<UserProfile>("/auth/me").then(r => r.data),
};

// ===================== QUERY =====================

export const queryAPI = {
  ask: (data: QueryRequest) =>
    apiClient.post<QueryResponse>("/query/ask", data).then(r => r.data),

  // SSE streaming — returns EventSource-compatible URL + token
  askStreamUrl: () => `${BASE_URL}/query/ask/stream`,

  history: (limit = 10, offset = 0) =>
    apiClient.get<QueryHistoryResponse>("/query/history", { params: { limit, offset } }).then(r => r.data),

  getQuery: (queryId: string) =>
    apiClient.get<QueryResponse>(`/query/${queryId}`).then(r => r.data),

  submitFeedback: (data: FeedbackRequest) =>
    apiClient.post("/query/feedback", data).then(r => r.data),
};

// SSE streaming helper
export function createQueryStream(
  data: QueryRequest,
  onEvent: (event: string, payload: unknown) => void,
  onError?: (error: Error) => void
): () => void {
  const token = Cookies.get("neethi_token");

  let aborted = false;
  const controller = new AbortController();

  fetch(`${BASE_URL}/query/ask/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
      "Accept": "text/event-stream",
    },
    body: JSON.stringify(data),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";

      while (!aborted) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const chunk of lines) {
          if (!chunk.trim()) continue;

          let eventType = "message";
          let eventData = "";

          for (const line of chunk.split("\n")) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              eventData = line.slice(6).trim();
            }
          }

          if (eventData) {
            try {
              const parsed = JSON.parse(eventData);
              onEvent(eventType, parsed);
            } catch {
              onEvent(eventType, eventData);
            }
          }
        }
      }
    })
    .catch((err) => {
      if (!aborted && onError) {
        onError(err instanceof Error ? err : new Error(String(err)));
      }
    });

  return () => {
    aborted = true;
    controller.abort();
  };
}

// ===================== CONVERSATION =====================

export const conversationAPI = {
  turn: (data: TurnRequest) =>
    apiClient.post<TurnResponse>("/conversation/turn", data).then(r => r.data),

  getSession: (sessionId: string) =>
    apiClient.get<SessionResponse>(`/conversation/session/${sessionId}`).then(r => r.data),
};

// SSE streaming helper for conversation turns
export function createTurnStream(
  data: TurnRequest,
  onEvent: (event: string, payload: unknown) => void,
  onError?: (error: Error) => void
): () => void {
  const token = Cookies.get("neethi_token");

  let aborted = false;
  const controller = new AbortController();

  fetch(`${BASE_URL}/conversation/turn/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
      "Accept": "text/event-stream",
    },
    body: JSON.stringify(data),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";

      while (!aborted) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const chunk of lines) {
          if (!chunk.trim()) continue;

          let eventType = "message";
          let eventData = "";

          for (const line of chunk.split("\n")) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              eventData = line.slice(6).trim();
            }
          }

          if (eventData) {
            try {
              const parsed = JSON.parse(eventData);
              onEvent(eventType, parsed);
            } catch {
              onEvent(eventType, eventData);
            }
          }
        }
      }
    })
    .catch((err) => {
      if (!aborted && onError) {
        onError(err instanceof Error ? err : new Error(String(err)));
      }
    });

  return () => {
    aborted = true;
    controller.abort();
  };
}

// ===================== DOCUMENT ANALYSIS STREAMING =====================

/**
 * Stream document analysis via PageIndex.
 * Emits SSE events: status | complete | error | end
 */
export function createDocumentAnalysisStream(
  file: File,
  query: string,
  onEvent: (event: string, payload: unknown) => void,
  onError?: (error: Error) => void,
): () => void {
  const token = Cookies.get("neethi_token");
  let aborted = false;
  const controller = new AbortController();

  const form = new FormData();
  form.append("file", file, file.name);
  form.append("query", query);

  fetch(`${BASE_URL}/documents/analyze/stream`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token ?? ""}`,
      Accept: "text/event-stream",
    },
    body: form,
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const text = await response.text().catch(() => `HTTP ${response.status}`);
        throw new Error(text || `HTTP ${response.status}`);
      }
      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";

      while (!aborted) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";

        for (const chunk of chunks) {
          if (!chunk.trim()) continue;
          let eventType = "message";
          let eventData = "";
          for (const line of chunk.split("\n")) {
            if (line.startsWith("event: ")) eventType = line.slice(7).trim();
            else if (line.startsWith("data: ")) eventData = line.slice(6).trim();
          }
          if (eventData) {
            try { onEvent(eventType, JSON.parse(eventData)); }
            catch { onEvent(eventType, eventData); }
          }
        }
      }
    })
    .catch((err) => {
      if (!aborted && onError) {
        onError(err instanceof Error ? err : new Error(String(err)));
      }
    });

  return () => { aborted = true; controller.abort(); };
}

// ===================== CASES =====================

export const casesAPI = {
  search: (data: CaseSearchRequest) =>
    apiClient.post<CaseSearchResponse>("/cases/search", data).then(r => r.data),

  similarCases: (data: SimilarCasesRequest) =>
    apiClient.post<SimilarCasesResponse>("/cases/similar", data).then(r => r.data),

  analyze: (data: CaseAnalysisRequest) =>
    apiClient.post<CaseAnalysisResponse>("/cases/analyze", data).then(r => r.data),

  getCase: (caseId: string) =>
    apiClient.get<CaseDetail>(`/cases/${caseId}`).then(r => r.data),
};

// ===================== DOCUMENTS =====================

export const documentsAPI = {
  listTemplates: () =>
    apiClient.get<TemplateListResponse>("/documents/templates").then(r => r.data),

  createDraft: (data: DraftRequest) =>
    apiClient.post<DraftResponse>("/documents/draft", data).then(r => r.data),

  getDraft: (draftId: string) =>
    apiClient.get<DraftResponse>(`/documents/draft/${draftId}`).then(r => r.data),

  updateDraft: (draftId: string, data: DraftUpdateRequest) =>
    apiClient.put<DraftResponse>(`/documents/draft/${draftId}`, data).then(r => r.data),

  deleteDraft: (draftId: string) =>
    apiClient.delete(`/documents/draft/${draftId}`).then(r => r.data),

  exportPDF: async (draftId: string): Promise<Blob> => {
    const response = await apiClient.post(`/documents/draft/${draftId}/pdf`, {}, {
      responseType: "blob",
    });
    return response.data;
  },

};

// ===================== SECTIONS =====================

export const sectionsAPI = {
  listActs: () =>
    apiClient.get<ActListResponse>("/sections/acts").then(r => r.data),

  listSections: (actCode: string, limit = 50, offset = 0, chapter?: string, isOffence?: boolean) =>
    apiClient.get(`/sections/acts/${actCode}/sections`, {
      params: { limit, offset, chapter, is_offence: isOffence },
    }).then(r => r.data),

  getSection: (actCode: string, sectionNumber: string) =>
    apiClient.get<SectionDetail>(`/sections/acts/${actCode}/sections/${sectionNumber}`).then(r => r.data),

  normalize: (oldAct: string, oldSection: string) =>
    apiClient.get<NormalizeResponse>("/sections/normalize", {
      params: { old_act: oldAct, old_section: oldSection },
    }).then(r => r.data),

  verify: (data: VerifyRequest) =>
    apiClient.post<VerifyResponse>("/sections/verify", data).then(r => r.data),
};

// ===================== RESOURCES =====================

export const resourcesAPI = {
  findNearby: (data: NearbyRequest) =>
    apiClient.post<NearbyResponse>("/resources/nearby", data).then(r => r.data),


};

// ===================== TRANSLATION =====================

export const translateAPI = {
  translateText: (data: TranslateTextRequest) =>
    apiClient.post<TranslateTextResponse>("/translate/text", data).then(r => r.data),

  translateQuery: (data: TranslateQueryRequest) =>
    apiClient.post<TranslateQueryResponse>("/translate/query", data).then(r => r.data),
};

// ===================== ADMIN =====================

export const adminAPI = {
  health: () =>
    apiClient.get<HealthResponse>("/admin/health").then(r => r.data),

  flushCache: (role = "all") =>
    apiClient.post("/admin/cache/flush", { role }).then(r => r.data),

  toggleMistralFallback: (active: boolean) =>
    apiClient.post("/admin/mistral-fallback", { active }).then(r => r.data),

  getStats: () =>
    apiClient.get<AdminStats>("/admin/stats").then(r => r.data),

  listUsers: (params?: { role?: string; is_active?: boolean; search?: string; limit?: number; offset?: number }) =>
    apiClient.get<UserListResponse>("/admin/users", { params }).then(r => r.data),

  getUser: (userId: string) =>
    apiClient.get<UserDetailResponse>(`/admin/users/${userId}`).then(r => r.data),

  updateUser: (userId: string, data: UserUpdateRequest) =>
    apiClient.patch<UserDetailResponse>(`/admin/users/${userId}`, data).then(r => r.data),

  getActivity: (params?: { role?: string; limit?: number; offset?: number }) =>
    apiClient.get<ActivityResponse>("/admin/activity", { params }).then(r => r.data),
};

// ===================== VOICE =====================

export const voiceAPI = {
  /**
   * Send an audio blob to the backend STT→process→TTS pipeline.
   * @param audioBlob  recorded audio (webm / wav)
   * @param language   Sarvam language code, e.g. "hi-IN"
   */
  ask: async (audioBlob: Blob, language = "en-IN") => {
    const form = new FormData();
    form.append("file", audioBlob, "recording.wav");
    form.append("language_code", language);
    const token = Cookies.get("neethi_token");
    const res = await fetch(`${BASE_URL}/voice/ask`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token ?? ""}` },
      body: form,
    });
    if (!res.ok) throw new Error(`Voice API error: ${res.status}`);
    return res.json();
  },

  /**
   * Convert text to speech using Sarvam AI (bulbul:v2).
   * Returns an audio/wav Blob for playback via the browser Audio API.
   */
  textToSpeech: async (
    text: string,
    languageCode = "en-IN",
    speaker: "anushka" | "manisha" | "vidya" | "arjun" | "abhilash" | "ishaan" = "anushka"
  ): Promise<Blob> => {
    const token = Cookies.get("neethi_token");
    const res = await fetch(`${BASE_URL}/voice/text-to-speech`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token ?? ""}`,
      },
      body: JSON.stringify({
        text: text.slice(0, 3000),
        target_language_code: languageCode,
        speaker,
        pitch: 0,
        pace: 1.0,
        loudness: 1.5,
        speech_sample_rate: 16000,
        enable_preprocessing: true,
      }),
    });
    if (!res.ok) {
      const errText = await res.text().catch(() => `status ${res.status}`);
      throw new Error(`TTS error ${res.status}: ${errText}`);
    }
    return res.blob();
  },

  /**
   * Convert audio to text using Sarvam AI (saarika:v2.5).
   * Returns the transcript string.
   */
  speechToText: async (audioBlob: Blob, languageCode = "hi-IN"): Promise<string> => {
    const token = Cookies.get("neethi_token");
    const form = new FormData();
    form.append("file", audioBlob, "recording.wav");
    form.append("language_code", languageCode);
    const res = await fetch(`${BASE_URL}/voice/speech-to-text`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token ?? ""}` },
      body: form,
    });
    if (!res.ok) {
      const errText = await res.text().catch(() => `status ${res.status}`);
      throw new Error(`STT error ${res.status}: ${errText}`);
    }
    const data = await res.json();
    return (data.transcript as string) ?? "";
  },
};

// ===================== PUBLIC HEALTH =====================

export const publicAPI = {
  health: () => axios.get("/health").then(r => r.data),
};

export default apiClient;
