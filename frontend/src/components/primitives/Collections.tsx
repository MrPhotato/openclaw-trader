import type { ReactNode } from "react";

import type { AssetRecord } from "../../lib/types";
import { EmptyState } from "./EmptyState";

export function renderCollection<T>(
  items: T[],
  renderItem: (item: T, index: number) => ReactNode,
  emptyMessage: string,
): ReactNode {
  if (items.length === 0) {
    return <EmptyState message={emptyMessage} />;
  }
  return items.map((item, index) => renderItem(item, index));
}

export function renderAssetCollection(
  items: AssetRecord[],
  renderItem: (item: AssetRecord, index: number) => ReactNode,
  emptyMessage: string,
): ReactNode {
  return renderCollection(items, renderItem, emptyMessage);
}
