/** Node outlines. Org/gov = browse trapezoid. Person = a 32px disc on the bar.
 * The disc is a badge: Sankey height is flow, a face must not stretch with it.
 */

export const BADGE = 32;

export const USER_BODY = "M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2";

export function trapezoidPath(d) {
  const midY = (d.y0 + d.y1) / 2;
  const dx = Math.max(d.x1 - d.x0, 1);
  let inflow = d.inflowHeight || d.y1 - d.y0;
  let outflow = d.outflowHeight || d.y1 - d.y0;
  if (inflow < dx && outflow < dx) {
    inflow = dx / 2;
    outflow = dx / 2;
  }
  const y0In = midY - inflow / 2;
  const y1In = midY + inflow / 2;
  const y0Out = midY - outflow / 2;
  const y1Out = midY + outflow / 2;
  return `M${d.x0},${y0In} L${d.x0},${y1In} L${d.x1},${y1Out} L${d.x1},${y0Out} Z`;
}

export function badgeCenter(d) {
  return {
    x: (d.x0 + d.x1) / 2,
    y: (d.y0 + d.y1) / 2,
  };
}

export function linkPath(d) {
  if (d.circular && d.path) return d.path;
  const x0 = d.source.x1;
  const x1 = d.target.x0;
  const y0 = d.y0;
  const y1 = d.y1;
  const mid = (x0 + x1) / 2;
  return `M${x0},${y0}C${mid},${y0} ${mid},${y1} ${x1},${y1}`;
}
