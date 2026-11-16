import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = readFileSync(
  path.resolve(process.cwd(), "app/(workspace)/learning/books/BooksRoute.tsx"),
  "utf8",
);

test("BooksRoute forwards the custom deep-dive identity to the API", () => {
  assert.match(
    source,
    /onDeepDive=\{\(topic, blockId, customTopic\) =>\s*canEditBook \? handleDeepDive\(topic, blockId, customTopic\) : undefined/,
  );
  assert.match(source, /\.\.\.\(customTopic \? \{ custom_topic: true \} : \{\}\)/);
});

test("controlled books route block lifecycle through extensions and hide rebuild", () => {
  assert.ok(source.includes("bookApi.deleteExtensionBlock({"));
  assert.ok(source.includes("bookApi.regenerateExtensionBlock({"));
  assert.ok(source.includes("protectedContent={Boolean(detail?.book.metadata?.learning_question_controlled)}"));
  assert.ok(source.includes("onRebuild={detail && canEditBook && !detail.book.metadata?.learning_question_controlled"));
  const reader = readFileSync(
    path.resolve(process.cwd(), "app/(workspace)/learning/books/components/PageReader.tsx"),
    "utf8",
  );
  assert.ok(reader.includes("canRegenerate(block) ? onRegenerateBlock : undefined"));
  assert.ok(reader.includes("canDelete(block) ? onDeleteBlock : undefined"));
  assert.ok(reader.includes("canEdit(block) ? onUpdateBody : undefined"));
});
