/** Thin, static top-face rings for blocks named by the pure validator. */
import { Line } from "@react-three/drei";
import { blockSceneSize, cellToScene } from "../coords";
import type { ModelBlock } from "../model";
import type { Diagnostic, DiagnosticSeverity } from "../validate";
import { tokenColor } from "./theme";

const severityFor = (current: DiagnosticSeverity | undefined, next: DiagnosticSeverity) =>
  current === "error" || next === "error" ? "error" : "warning";

export function DiagnosticMarkers({ blocks, diagnostics, emphasizedId }: {
  blocks: ModelBlock[];
  diagnostics: Diagnostic[];
  emphasizedId?: string | null;
}) {
  const severity = new Map<string, DiagnosticSeverity>();
  diagnostics.forEach(item => {
    if (item.blockId) severity.set(item.blockId, severityFor(severity.get(item.blockId), item.severity));
  });
  return (
    <>
      {blocks.flatMap(block => {
        const level = severity.get(block.id);
        if (!level) return [];
        const centre = cellToScene(block.mode, block.col, block.row, block.level);
        const size = blockSceneSize(block.mode);
        const lift = centre.y + size.y / 2 + 0.02;
        const scale = emphasizedId === block.id ? 1.08 : 1;
        const halfX = size.x * scale / 2;
        const halfZ = size.z * scale / 2;
        return [(
          <Line key={block.id}
                points={[
                  [centre.x - halfX, lift, centre.z - halfZ],
                  [centre.x + halfX, lift, centre.z - halfZ],
                  [centre.x + halfX, lift, centre.z + halfZ],
                  [centre.x - halfX, lift, centre.z + halfZ],
                  [centre.x - halfX, lift, centre.z - halfZ],
                ]}
                color={tokenColor(level === "error" ? "--danger" : "--motion")}
                lineWidth={emphasizedId === block.id ? 2 : 1}
                raycast={() => null} />
        )];
      })}
    </>
  );
}
