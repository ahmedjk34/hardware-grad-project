/**
 * The Studio's colours are the console's colours.
 *
 * DESIGN.md section 3.1 says nothing in a component carries a raw colour value,
 * and that rule does not stop at the edge of a WebGL canvas. Every material in
 * `scene/` asks for a token by name and this module reads it off the document,
 * so the Studio and the console cannot drift apart.
 */
import { CanvasTexture, Color, RepeatWrapping, type Texture } from "three";

const cache = new Map<string, string>();
const colourCache = new Map<string, Color>();

/** The computed value of a custom property, or "" when there is no stylesheet. */
export function cssToken(name: string): string {
  const hit = cache.get(name);
  if (hit !== undefined) return hit;
  const value = typeof window === "undefined" ? ""
    : getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  cache.set(name, value);
  return value;
}

/** A token as a three.js colour. An unreadable token stays three's own default
 *  rather than being replaced by a literal nobody designed. */
export function tokenColor(name: string): Color {
  const hit = colourCache.get(name);
  if (hit) return hit;
  const colour = new Color();
  const value = cssToken(name);
  if (value) colour.setStyle(value);
  colourCache.set(name, colour);
  return colour;
}

/**
 * The feeder's hatch, drawn rather than shipped: an asset would be one more
 * file the Pi has to serve, and the stripes have to follow the tokens anyway.
 */
export function hatchTexture(token: string, size = 32): Texture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const context = canvas.getContext("2d");
  const stroke = cssToken(token);
  if (context && stroke) {
    context.strokeStyle = stroke;
    context.lineWidth = 2;
    context.beginPath();
    for (let offset = -size; offset < size * 2; offset += size / 4) {
      context.moveTo(offset, 0);
      context.lineTo(offset + size, size);
    }
    context.stroke();
  }
  const texture = new CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = RepeatWrapping;
  return texture;
}
