/** The exact placement a click would commit; absent means no click target. */
import { Edges, Html, RoundedBox } from "@react-three/drei";
import { blockSceneSize, cellToScene, type ModeName, type Shift } from "../coords";
import type { CellTarget } from "../pick";
import type { DiagnosticSeverity } from "../validate";
import { tokenColor } from "./theme";

export interface GhostStatus {
  legal: boolean;
  reason: string | null;
  severity: DiagnosticSeverity | null;
}

export function Ghost({ mode, shift, target, status }: {
  mode: ModeName;
  shift?: Shift;
  target: CellTarget | null;
  status: GhostStatus | null;
}) {
  if (!target || !status) return null;
  const position = cellToScene(mode, target.col, target.row, target.level, shift);
  const size = blockSceneSize(mode);
  const token = status.severity === "error" ? "--danger"
    : status.severity === "warning" ? "--motion" : "--signal";
  return (
    <RoundedBox
      args={[size.x, size.y, size.z]}
      radius={0.06}
      smoothness={4}
      position={[position.x, position.y, position.z]}
      raycast={() => null}
    >
      <meshStandardMaterial
        color={tokenColor(token)} transparent opacity={status.legal ? 0.35 : 0.30}
        depthWrite={false} roughness={0.55} metalness={0}
      />
      <Edges color={tokenColor(token)} threshold={20} />
      {status.reason ? (
        <Html position={[0, size.y / 2, 0]} style={{ transform: "translate(14px, 14px)" }}>
          <span className={`studio-tag studio-ghost-reason studio-ghost-${status.severity ?? "valid"}`}>
            {status.reason}
          </span>
        </Html>
      ) : null}
    </RoundedBox>
  );
}
