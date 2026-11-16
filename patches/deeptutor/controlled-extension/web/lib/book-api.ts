import { activeWorkspaceId, scopedUrl } from "@/lib/workspace-scope";
import { randomUuid } from "@/lib/random-uuid";
import { apiFetch, apiUrl, wsUrl } from "@/lib/api";
import {
  BookSocketOperationError,
  runBookSocketOperation,
  type BookWsEvent,
} from "@/lib/book-ws-operation";
import type {
  Book,
  BookDepth,
  BookDetail,
  LearningCapture,
  LearningCaptureStatus,
  BookProposal,
  Page,
  Progress,
  Spine,
  Block,
  GenerationSummary,
} from "@/lib/book-types";

const BASE = "/api";
const BOOK_WS_PATH = "/ws/books";

export class BookApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
    public readonly currentRevision?: number,
  ) {
    super(message);
    this.name = "BookApiError";
  }
}

function requestOverSocket<T extends BookWsEvent>(
  message: BookWsEvent,
  resultType: string,
  onEvent?: (event: BookWsEvent) => void,
): Promise<T> {
  return runBookSocketOperation<T>(() => new WebSocket(wsUrl(BOOK_WS_PATH)), {
    message,
    resultType,
    onEvent,
  }).catch((error) => {
    if (error instanceof BookSocketOperationError && error.status) {
      throw new BookApiError(
        error.message,
        error.status,
        error.code,
        error.currentRevision,
      );
    }
    throw error;
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(apiUrl(`${BASE}${path}`), {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail: string;
    let code: string | undefined;
    let currentRevision: number | undefined;
    try {
      const data = await res.json();
      const raw = data && (data.detail || data.message);
      if (raw && typeof raw === "object") {
        detail = String(raw.message || raw.code || res.statusText);
        code = raw.code ? String(raw.code) : undefined;
        currentRevision =
          typeof raw.current_revision === "number"
            ? raw.current_revision
            : undefined;
      } else {
        detail = String(raw || res.statusText);
      }
    } catch {
      detail = res.statusText;
    }
    throw new BookApiError(
      `book api ${path} → ${res.status}: ${detail}`,
      res.status,
      code,
      currentRevision,
    );
  }
  return (await res.json()) as T;
}

export interface CreateBookPayload {
  source_refs?: import("@/lib/learning-api").TopicSourceInput[];
  user_intent: string;
  chat_session_id?: string;
  chat_selections?: Array<{ session_id: string; message_ids: number[] }>;
  notebook_refs?: Array<Record<string, unknown>>;
  knowledge_bases?: string[];
  question_categories?: number[];
  question_entries?: number[];
  language?: string;
  fallback_language?: string;
  depth?: BookDepth;
}

/** Per-chapter generation cost, keyed by content type. */
export interface EstimateBasis {
  [contentType: string]: { blocks: number; words: number; seconds: number };
}

type ExtensionOperation = "append_blocks" | "supplement" | "deep_dive" | "remove_block" | "regenerate_block";
type ExtensionBinding = Record<string, unknown>;
type ExtensionFields = Record<string, unknown>;

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map(key =>
    `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
}

export async function extensionDigest(payload: ExtensionFields): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson({
    rule: "learning-extension-request/1",
    payload,
  }));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}

type PendingExtension = {
  schema: "learning-extension-pending/1";
  path: string;
  operation: ExtensionOperation;
  payload: ExtensionFields;
};

function pendingStorage(): Storage {
  if (typeof window === "undefined") {
    throw new BookApiError("当前环境不能保存学习扩展请求", 409, "extension_request_persistence");
  }
  return window.localStorage;
}

async function pendingKey(path: string, operation: ExtensionOperation, fields: ExtensionFields) {
  const semantic = { ...fields };
  delete semantic.expected_revision;
  const digest = await extensionDigest({ path, operation, fields: semantic });
  return `learning-extension:v1:${activeWorkspaceId()}:${digest}`;
}

function readPending(key: string): PendingExtension | null {
  const raw = pendingStorage().getItem(key);
  if (!raw) return null;
  const value = JSON.parse(raw) as PendingExtension;
  if (value.schema !== "learning-extension-pending/1" || !value.payload.request_id) {
    throw new BookApiError("本地学习扩展请求记录无效", 409, "extension_request_persistence");
  }
  return value;
}

async function postPending<T>(key: string, pending: PendingExtension): Promise<T> {
  const result = await request<T>(pending.path, {
    method: "POST",
    body: JSON.stringify(pending.payload),
  });
  pendingStorage().removeItem(key);
  return result;
}

async function retryGenerated<T>(
  key: string,
  pending: PendingExtension,
  fields: ExtensionFields,
): Promise<T> {
  const expectedRevision = Number(fields.expected_revision);
  const previousRevision = Number(pending.payload.expected_revision);
  if (!Number.isInteger(expectedRevision) || expectedRevision <= previousRevision) {
    throw new BookApiError("学习扩展 revision 未更新，不能复用候选", 409, "extension_revision");
  }
  const payload: ExtensionFields = {
    book_id: String(pending.payload.book_id),
    source_request_id: String(pending.payload.source_request_id || pending.payload.request_id),
    expected_revision: expectedRevision,
    request_id: randomUuid(),
    extension_id: randomUuid(),
    extension_binding: pending.payload.extension_binding,
  };
  payload.request_digest = await extensionDigest(payload);
  const retry: PendingExtension = {
    schema: "learning-extension-pending/1",
    path: "/books/retry-extension",
    operation: pending.operation,
    payload,
  };
  pendingStorage().setItem(key, JSON.stringify(retry));
  return postPending<T>(key, retry);
}

async function extensionRequest<T>(
  path: string,
  operation: ExtensionOperation,
  fields: ExtensionFields,
): Promise<T> {
  const key = await pendingKey(path, operation, fields);
  const existing = readPending(key);
  if (existing) {
    const bookId = String(existing.payload.book_id);
    const requestId = String(existing.payload.request_id);
    let status: { state?: string } | null;
    try {
      status = await request<{ state?: string }>(
        `/books/extensions/${encodeURIComponent(requestId)}?book_id=${encodeURIComponent(bookId)}`,
      );
    } catch (error) {
      if (error instanceof BookApiError && error.status === 404) status = null;
      else throw error;
    }
    if (status?.state === "committed") {
      pendingStorage().removeItem(key);
      return status as T;
    }
    if (status && status.state !== "generated") {
      throw new BookApiError(
        "原学习扩展结果尚未确定，请稍后再次点击原操作检查结果，不会重新生成",
        409,
        "extension_result_pending",
      );
    }
    try {
      return await postPending<T>(key, existing);
    } catch (error) {
      if (error instanceof BookApiError && error.code === "extension_revision") {
        return retryGenerated<T>(key, existing, fields);
      }
      throw error;
    }
  }

  const bookId = String(fields.book_id);
  const context = await request<{ extension_binding: ExtensionBinding }>(
    `/books/${encodeURIComponent(bookId)}/extension-context?operation=${encodeURIComponent(operation)}`,
  );
  const payload: ExtensionFields = {
    ...fields,
    request_id: randomUuid(),
    extension_id: randomUuid(),
    extension_binding: context.extension_binding,
  };
  payload.request_digest = await extensionDigest(payload);
  const pending: PendingExtension = { schema: "learning-extension-pending/1", path, operation, payload };
  pendingStorage().setItem(key, JSON.stringify(pending));
  return postPending<T>(key, pending);
}

export const bookApi = {
  list: () => request<{ books: Book[]; can_create: boolean }>("/books"),

  /**
   * Cost of one chapter of each content type, at a given depth.
   *
   * Fetched once; the spine editor sums it locally so the estimate stays live
   * while chapters are edited. The numbers derive from the same templates the
   * architect plans from, so they cannot drift from reality.
   */
  estimateBasis: (depth: BookDepth = "standard") =>
    request<{ depth: string; basis: EstimateBasis }>(
      `/estimate-basis?depth=${encodeURIComponent(depth)}`,
    ),
  /**
   * Load a book.
   *
   * `includeBlocks: false` returns chapter metadata without block payloads —
   * a compiled book's blocks carry their whole rendered content, so the full
   * response runs to hundreds of kilobytes. Views that only need the chapter
   * list should ask for summaries.
   */
  get: (book_id: string, options?: { includeBlocks?: boolean }) =>
    request<BookDetail>(
      `/books/${encodeURIComponent(book_id)}` +
        (options?.includeBlocks === false ? "?include_blocks=false" : ""),
    ),
  delete: (book_id: string, workspaceId = activeWorkspaceId()) =>
    request<{ deleted: boolean; book_id: string }>(
      scopedUrl(`/books/${encodeURIComponent(book_id)}`, workspaceId),
      {
        method: "DELETE",
      },
    ),
  getSpine: (book_id: string) =>
    request<{ spine: Spine }>(`/books/${encodeURIComponent(book_id)}/spine`),
  getPage: (book_id: string, page_id: string) =>
    request<{ page: Page }>(
      `/books/${encodeURIComponent(book_id)}/pages/${encodeURIComponent(page_id)}`,
    ),
  create: (
    payload: CreateBookPayload,
    onEvent?: (event: BookWsEvent) => void,
  ) =>
    requestOverSocket<{
      type: "create_result";
      book: Book;
      proposal: BookProposal;
    }>({ type: "create", ...payload }, "create_result", onEvent),
  confirmProposal: (
    book_id: string,
    proposal?: BookProposal,
    expected_revision?: number,
    onEvent?: (event: BookWsEvent) => void,
  ) =>
    requestOverSocket<{
      type: "confirm_proposal_result";
      book: Book;
      spine: Spine;
      book_revision: number;
    }>(
      {
        type: "confirm_proposal",
        book_id,
        proposal: proposal ?? null,
        expected_revision,
      },
      "confirm_proposal_result",
      onEvent,
    ),
  confirmSpine: (
    book_id: string,
    spine?: Spine,
    auto_compile = true,
    expected_revision?: number,
    /**
     * Which block types the chapters may contain. `undefined` leaves the
     * book's current choice alone; `[]` clears it back to no restriction.
     */
    block_types?: string[],
  ) =>
    request<{ pages: Page[]; book_revision: number }>("/books/confirm-spine", {
      method: "POST",
      body: JSON.stringify({
        book_id,
        spine: spine ?? null,
        auto_compile,
        expected_revision,
        block_types: block_types ?? null,
      }),
    }),

  /** The block types the architect can plan, straight from the planner. */
  blockTypes: () =>
    request<{
      block_types: Array<{ value: string; planner_default: boolean }>;
    }>("/books/block-types"),
  compilePage: (
    book_id: string,
    page_id: string,
    force = false,
    expected_revision?: number,
    onEvent?: (event: BookWsEvent) => void,
  ) =>
    requestOverSocket<{
      type: "compile_page_result";
      page: Page;
      book_revision: number;
    }>(
      { type: "compile_page", book_id, page_id, force, expected_revision },
      "compile_page_result",
      onEvent,
    ),
  regenerateBlock: (
    book_id: string,
    page_id: string,
    block_id: string,
    params_override?: Record<string, unknown>,
    expected_revision?: number,
    onEvent?: (event: BookWsEvent) => void,
  ) =>
    requestOverSocket<{
      type: "regenerate_block_result";
      block: Block | null;
      book_revision: number;
    }>(
      {
        type: "regenerate_block",
        book_id,
        page_id,
        block_id,
        params_override: params_override ?? null,
        expected_revision,
      },
      "regenerate_block_result",
      onEvent,
    ),

  insertBlock: (params: {
    book_id: string;
    page_id: string;
    block_type: string;
    params?: Record<string, unknown>;
    position?: number;
    compile_now?: boolean;
    expected_revision?: number;
  }) =>
    request<{ block: Block; book_revision: number }>("/books/insert-block", {
      method: "POST",
      body: JSON.stringify({
        compile_now: true,
        ...params,
      }),
    }),

  /** Edit a block's prose in place. Title/body only — see the backend note. */
  updateBlock: (params: {
    book_id: string;
    page_id: string;
    block_id: string;
    title?: string;
    body?: string;
    expected_revision?: number;
  }) =>
    request<{ block: Block; book_revision: number }>("/books/update-block", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  markVisited: (book_id: string, page_id: string) =>
    request<{ progress: Progress }>("/books/progress/visit", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id }),
    }),

  toggleBookmark: (book_id: string, page_id: string) =>
    request<{ progress: Progress }>("/books/progress/bookmark", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id }),
    }),

  /** Href for the Markdown download — a plain link, so the browser saves it. */
  exportUrl: (book_id: string) =>
    apiUrl(`${BASE}/books/${encodeURIComponent(book_id)}/export`),

  deleteBlock: (
    book_id: string,
    page_id: string,
    block_id: string,
    expected_revision?: number,
  ) =>
    request<{ ok: boolean; book_revision: number }>("/books/delete-block", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id, block_id, expected_revision }),
    }),

  moveBlock: (
    book_id: string,
    page_id: string,
    block_id: string,
    new_position: number,
    expected_revision?: number,
  ) =>
    request<{ ok: boolean; book_revision: number }>("/books/move-block", {
      method: "POST",
      body: JSON.stringify({
        book_id,
        page_id,
        block_id,
        new_position,
        expected_revision,
      }),
    }),

  changeBlockType: (params: {
    book_id: string;
    page_id: string;
    block_id: string;
    new_type: string;
    params_override?: Record<string, unknown>;
    expected_revision?: number;
  }) =>
    request<{ block: Block; book_revision: number }>(
      "/books/change-block-type",
      {
        method: "POST",
        body: JSON.stringify(params),
      },
    ),

  deepDive: (params: {
    book_id: string;
    parent_page_id: string;
    topic: string;
    block_id?: string;
    content_type?: string;
    expected_revision?: number;
  }) =>
    request<{ page: Page; book_revision: number }>("/books/deep-dive", {
      method: "POST",
      body: JSON.stringify({ content_type: "concept", ...params }),
    }),

  recordQuizAttempt: (params: {
    book_id: string;
    page_id: string;
    block_id: string;
    question_id?: string;
    user_answer?: string;
    /** Omit for a written answer the reader revealed but didn't self-grade. */
    is_correct?: boolean;
    submission_id?: string;
  }) =>
    request<{ progress: Progress }>("/books/quiz-attempt", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  supplement: (
    book_id: string,
    page_id: string,
    topic: string,
    expected_revision?: number,
  ) =>
    request<{ block: Block; book_revision: number }>("/books/supplement", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id, topic, expected_revision }),
    }),

  setPageChatSession: (book_id: string, page_id: string, session_id: string) =>
    request<{ book: Book }>("/books/page-chat-session", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id, session_id }),
    }),

  /** Re-queue unfinished pages, keeping everything already compiled. */
  resume: (book_id: string, expected_revision?: number) =>
    request<{ pages: Page[]; book_revision: number }>("/books/resume", {
      method: "POST",
      body: JSON.stringify({ book_id, expected_revision }),
    }),

  /** Stop queued and in-flight generation while preserving completed output. */
  pause: (book_id: string, expected_revision?: number) =>
    request<{ pages: Page[]; book_revision: number }>("/books/pause", {
      method: "POST",
      body: JSON.stringify({ book_id, expected_revision }),
    }),

  /** Destructive: discards every page and regenerates from the spine. */
  rebuild: (book_id: string, auto_compile = true, expected_revision?: number) =>
    request<{ pages: Page[]; book_revision: number }>("/books/rebuild", {
      method: "POST",
      body: JSON.stringify({ book_id, auto_compile, expected_revision }),
    }),

  health: (book_id: string) =>
    request<{
      kb_drift: {
        book_id: string;
        has_drift: boolean;
        new_kbs?: string[];
        removed_kbs?: string[];
        changed_kbs?: string[];
        stale_page_ids?: string[];
      };
      log_health: {
        book_id: string;
        total_entries: number;
        error_entries: number;
        block_failures: number;
        last_compile_at?: string;
        last_error_at?: string;
        repeated_failures?: { signature: string; count: number }[];
      };
      generation: GenerationSummary;
    }>(`/books/${encodeURIComponent(book_id)}/health`),

  /** Mark the current KB state as seen. Rejected with 409 while pages the last
   *  drift flagged are still awaiting recompilation; `force` dismisses anyway. */
  refreshFingerprints: (
    book_id: string,
    force = false,
    expected_revision?: number,
  ) =>
    request<{
      book_id: string;
      kb_fingerprints: Record<string, string>;
      stale_page_ids: string[];
      book_revision: number;
    }>(
      `/books/${encodeURIComponent(book_id)}/refresh-fingerprints?force=${
        force ? "true" : "false"
      }${expected_revision ? `&expected_revision=${expected_revision}` : ""}`,
      { method: "POST" },
    ),

  listLearningCaptures: (book_id: string, status?: LearningCaptureStatus) =>
    request<{ captures: LearningCapture[] }>(
      `/books/${encodeURIComponent(
        book_id,
      )}/learning-captures${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),

  createLearningCapture: (
    book_id: string,
    payload: {
      page_id: string;
      block_id: string;
      source_text: string;
      context_before?: string;
      context_after?: string;
      source_locator?: string;
      book_title?: string;
      chapter_title?: string;
      user_note?: string;
      status?: LearningCaptureStatus;
    },
  ) =>
    request<{ capture: LearningCapture }>(
      `/books/${encodeURIComponent(book_id)}/learning-captures`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  generateExtension: (params: {
    book_id: string;
    page_id: string;
    block_type: string;
    params?: Record<string, unknown>;
    position?: number | null;
    expected_revision: number;
  }) => extensionRequest<{ blocks: Block[]; book_revision: number; publication: Record<string, unknown> }>(
    "/books/generate-extension", "append_blocks", params),

  generateSupplement: (params: {
    book_id: string;
    page_id: string;
    topic: string;
    position?: number | null;
    expected_revision: number;
  }) => extensionRequest<{ blocks: Block[]; book_revision: number; publication: Record<string, unknown> }>(
    "/books/generate-supplement-extension", "supplement", params),

  generateDeepDive: (params: {
    book_id: string;
    parent_page_id: string;
    block_id: string;
    topic: string;
    custom_topic?: boolean;
    expected_revision: number;
  }) => extensionRequest<{ page: Page; book_revision: number; publication: Record<string, unknown> }>(
    "/books/generate-deep-dive-extension", "deep_dive", params),

  deleteExtensionBlock: (params: {
    book_id: string;
    page_id: string;
    block_id: string;
    expected_revision: number;
  }) => extensionRequest<{ ok: boolean; blockId: string; book_revision: number; publication: Record<string, unknown> }>(
    "/books/delete-extension-block", "remove_block", params),

  regenerateExtensionBlock: (params: {
    book_id: string;
    page_id: string;
    block_id: string;
    expected_revision: number;
  }) => extensionRequest<{ block: Block; book_revision: number; publication: Record<string, unknown> }>(
    "/books/regenerate-extension-block", "regenerate_block", params),

  updateLearningCapture: (
    book_id: string,
    capture_id: string,
    payload: {
      status?: LearningCaptureStatus;
      user_note?: string;
      rejected_reason?: string;
    },
  ) =>
    request<{ capture: LearningCapture }>(
      `/books/${encodeURIComponent(book_id)}/learning-captures/${encodeURIComponent(capture_id)}`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
      },
    ),
};

// Re-exported so callers can keep importing the event type from book-api.
export type { BookWsEvent } from "@/lib/book-ws-operation";
