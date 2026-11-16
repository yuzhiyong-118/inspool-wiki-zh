import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DeepDiveBlock from "@/app/(workspace)/learning/books/components/blocks/DeepDiveBlock";
import type { Block } from "@/lib/book-types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/shared/ui/Tooltip", () => ({
  default: ({ children }: { children: React.ReactNode }) => children,
}));

const block: Block = {
  id: "blk_deep",
  type: "deep_dive",
  status: "ready",
  title: "深入学习",
  params: {},
  payload: { suggestions: [{ topic: "推荐方向", rationale: "推荐理由" }] },
  source_anchors: [],
  metadata: {},
  error: "",
  created_at: 1,
  updated_at: 1,
};

describe("DeepDiveBlock custom direction", () => {
  it("keeps recommended topics distinct from a trimmed custom direction", async () => {
    const onDeepDive = vi.fn().mockResolvedValue(undefined);
    render(<DeepDiveBlock block={block} onDeepDive={onDeepDive} />);

    fireEvent.click(screen.getByRole("button", { name: /推荐方向/ }));
    await waitFor(() => expect(onDeepDive).toHaveBeenLastCalledWith("推荐方向", "blk_deep", false));

    fireEvent.change(screen.getByRole("textbox", { name: "Custom deep dive direction" }), {
      target: { value: "  用户自己的方向  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate custom deep dive" }));
    await waitFor(() => expect(onDeepDive).toHaveBeenLastCalledWith("用户自己的方向", "blk_deep", true));
    expect(onDeepDive).toHaveBeenCalledTimes(2);
  });

  it("opens an existing custom subpage without generating it again", () => {
    const onDeepDive = vi.fn();
    const onOpenPage = vi.fn();
    const existing = {
      ...block,
      metadata: { deep_dive_pages: { "用户自己的方向": "pg_custom" } },
    };
    render(<DeepDiveBlock block={existing} onDeepDive={onDeepDive} onOpenPage={onOpenPage} />);

    fireEvent.change(screen.getByRole("textbox", { name: "Custom deep dive direction" }), {
      target: { value: "用户自己的方向" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate custom deep dive" }));
    expect(onOpenPage).toHaveBeenCalledWith("pg_custom");
    expect(onDeepDive).not.toHaveBeenCalled();
  });
});
