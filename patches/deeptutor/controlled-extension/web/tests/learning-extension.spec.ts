import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/api";
import { randomUuid } from "@/lib/random-uuid";
import { bookApi, extensionDigest } from "@/lib/book-api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
  wsUrl: (path: string) => path,
}));

vi.mock("@/lib/random-uuid", () => ({ randomUuid: vi.fn() }));

vi.mock("@/lib/workspace-scope", () => ({
  activeWorkspaceId: () => "ws-test",
  scopedUrl: (path: string) => path,
}));

function response(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as Response;
}

const fetchMock = vi.mocked(apiFetch);
const uuidMock = vi.mocked(randomUuid);
let localStorageMock: Storage;

beforeEach(() => {
  fetchMock.mockReset();
  uuidMock.mockReset();
  uuidMock.mockReturnValueOnce("request-1").mockReturnValueOnce("extension-1");
  const values = new Map<string, string>();
  localStorageMock = {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => { values.delete(key); },
    setItem: (key: string, value: string) => { values.set(key, value); },
  };
  vi.stubGlobal("window", { localStorage: localStorageMock });
});

afterEach(() => vi.unstubAllGlobals());

const fields = {
  book_id: "bk_1",
  page_id: "pg_1",
  block_type: "text",
  expected_revision: 4,
};

describe("learning extension request digest", () => {
  it("matches the backend canonical JSON and UTF-8 digest", async () => {
    await expect(extensionDigest({
      book_id: "bk_1",
      中文: "值",
      nested: { b: 2, a: 1 },
    })).resolves.toBe("4f969b4fe0fd25ad43493a6dd8ec52ebe2da29959fed1f453e066cfadce9abcf");
  });

  it("changes when the user intent changes", async () => {
    const base = { book_id: "bk_1", topic: "提交边界" };
    await expect(extensionDigest(base)).resolves.not.toBe(
      await extensionDigest({ ...base, topic: "前驱摘要" }),
    );
  });
});

describe("learning extension request reconciliation", () => {
  it("returns the committed result without generating a new request identity", async () => {
    fetchMock
      .mockResolvedValueOnce(response(200, { extension_binding: { source: "test" } }))
      .mockResolvedValueOnce(response(500, { detail: "lost response" }))
      .mockResolvedValueOnce(response(200, { state: "committed", blocks: [], book_revision: 5 }));

    await expect(bookApi.generateExtension(fields)).rejects.toMatchObject({ status: 500 });
    await expect(bookApi.generateExtension(fields)).resolves.toMatchObject({
      state: "committed",
      book_revision: 5,
    });

    const posted = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(posted.request_id).toBe("request-1");
    expect(fetchMock.mock.calls[2][0]).toContain("/books/extensions/request-1?");
    expect(uuidMock).toHaveBeenCalledTimes(2);
    expect(localStorageMock.length).toBe(0);
  });

  it("reuses the complete original request when a generated candidate can be committed", async () => {
    fetchMock
      .mockResolvedValueOnce(response(200, { extension_binding: { source: "test" } }))
      .mockResolvedValueOnce(response(500, { detail: "lost response" }))
      .mockResolvedValueOnce(response(200, { state: "generated" }))
      .mockResolvedValueOnce(response(200, { blocks: [], book_revision: 5 }));

    await expect(bookApi.generateExtension(fields)).rejects.toMatchObject({ status: 500 });
    await expect(bookApi.generateExtension({ ...fields, expected_revision: 5 })).resolves.toMatchObject({
      book_revision: 5,
    });

    const firstBody = String(fetchMock.mock.calls[1][1]?.body);
    const replayBody = String(fetchMock.mock.calls[3][1]?.body);
    expect(replayBody).toBe(firstBody);
    expect(uuidMock).toHaveBeenCalledTimes(2);
    expect(localStorageMock.length).toBe(0);
  });

  it("uses a linked request without regenerating after a revision conflict", async () => {
    uuidMock.mockReturnValueOnce("request-2").mockReturnValueOnce("extension-2");
    fetchMock
      .mockResolvedValueOnce(response(200, { extension_binding: { source: "test" } }))
      .mockResolvedValueOnce(response(409, { detail: { code: "extension_revision" } }))
      .mockResolvedValueOnce(response(200, { state: "generated" }))
      .mockResolvedValueOnce(response(409, { detail: { code: "extension_revision" } }))
      .mockResolvedValueOnce(response(200, { blocks: [], book_revision: 6 }));

    await expect(bookApi.generateExtension(fields)).rejects.toMatchObject({ status: 409 });
    await expect(bookApi.generateExtension({ ...fields, expected_revision: 5 })).resolves.toMatchObject({
      book_revision: 6,
    });

    expect(fetchMock.mock.calls[3][0]).toBe("/api/books/generate-extension");
    const retry = JSON.parse(String(fetchMock.mock.calls[4][1]?.body));
    expect(fetchMock.mock.calls[4][0]).toBe("/api/books/retry-extension");
    expect(retry.source_request_id).toBe("request-1");
    expect(retry.request_id).toBe("request-2");
    expect(retry.expected_revision).toBe(5);
    expect(uuidMock).toHaveBeenCalledTimes(4);
    expect(localStorageMock.length).toBe(0);
  });

  it("does not repost while the original result is uncertain", async () => {
    fetchMock
      .mockResolvedValueOnce(response(200, { extension_binding: { source: "test" } }))
      .mockResolvedValueOnce(response(500, { detail: "lost response" }))
      .mockResolvedValueOnce(response(200, { state: "uncertain" }));

    await expect(bookApi.generateExtension(fields)).rejects.toMatchObject({ status: 500 });
    await expect(bookApi.generateExtension(fields)).rejects.toMatchObject({
      status: 409,
      code: "extension_result_pending",
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(uuidMock).toHaveBeenCalledTimes(2);
    expect(localStorageMock.length).toBe(1);
  });

  it("uses dedicated lifecycle routes and operation bindings", async () => {
    uuidMock.mockReset();
    uuidMock.mockReturnValueOnce("delete-request").mockReturnValueOnce("delete-extension")
      .mockReturnValueOnce("regenerate-request").mockReturnValueOnce("regenerate-extension");
    fetchMock
      .mockResolvedValueOnce(response(200, { extension_binding: { operation: "remove_block" } }))
      .mockResolvedValueOnce(response(200, { ok: true, blockId: "blk_1", book_revision: 5 }))
      .mockResolvedValueOnce(response(200, { extension_binding: { operation: "regenerate_block" } }))
      .mockResolvedValueOnce(response(200, { block: { id: "blk_1" }, book_revision: 6 }));
    const lifecycle = { book_id: "bk_1", page_id: "pg_1", block_id: "blk_1", expected_revision: 4 };

    await expect(bookApi.deleteExtensionBlock(lifecycle)).resolves.toMatchObject({ ok: true });
    await expect(bookApi.regenerateExtensionBlock(lifecycle)).resolves.toMatchObject({ book_revision: 6 });

    expect(fetchMock.mock.calls[0][0]).toContain("operation=remove_block");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/books/delete-extension-block");
    expect(fetchMock.mock.calls[2][0]).toContain("operation=regenerate_block");
    expect(fetchMock.mock.calls[3][0]).toBe("/api/books/regenerate-extension-block");
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).request_id).toBe("delete-request");
    expect(JSON.parse(String(fetchMock.mock.calls[3][1]?.body)).request_id).toBe("regenerate-request");
  });
});
