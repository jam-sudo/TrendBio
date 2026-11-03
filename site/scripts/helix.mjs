import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';

const radius = 10, rise = 3.38, bpPerTurn = 10.5, turns = 3;
const offset = 140 * Math.PI / 180;
const twist = 2 * Math.PI / bpPerTurn;
const pitch = 160;
const scale = pitch / (rise * bpPerTurn);
const round = value => +value.toFixed(3);
const point = (bp, phase = 0) => ({
  x: bp * rise,
  y: radius * Math.cos(bp * twist + phase),
  z: radius * Math.sin(bp * twist + phase),
});
const project = p => ({ x: round(p.x * scale), y: round(60 - p.y * scale), z: round(p.z) });
const path = points => points.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' ');
const backbones = [0, offset].map(phase => {
  const samples = Array.from({ length: turns * bpPerTurn * 10 + 1 }, (_, i) => project(point(i / 10, phase)));
  const segments = [];
  let points = [samples[0]], front = samples[1].z > 0;
  for (let i = 1; i < samples.length; i++) {
    const a = samples[i - 1], b = samples[i];
    const nextFront = b.z > 0;
    if (nextFront !== front && b.z !== 0) {
      const t = -a.z / (b.z - a.z);
      const crossing = { x: round(a.x + t * (b.x - a.x)), y: round(a.y + t * (b.y - a.y)), z: 0 };
      points.push(crossing);
      segments.push({ front, d: path(points) });
      points = [crossing];
      front = nextFront;
    }
    points.push(b);
  }
  segments.push({ front, d: path(points) });
  return { samples, d: path(samples), segments };
});
const rungs = Array.from({ length: Math.floor(turns * bpPerTurn) + 1 }, (_, bp) => {
  const a = project(point(bp)), b = project(point(bp, offset));
  const cuts = [0, 1];
  if (a.z * b.z < 0) cuts.splice(1, 0, -a.z / (b.z - a.z));
  const segments = cuts.slice(1).map((end, i) => {
    const start = cuts[i], z = a.z + (b.z - a.z) * (start + end) / 2;
    return { x1: a.x, y1: round(a.y + (b.y - a.y) * start),
      x2: b.x, y2: round(a.y + (b.y - a.y) * end), front: z > 0,
      opacity: round((z > 0 ? 1 : .35) * (.75 + .25 * Math.abs(z) / radius)) };
  });
  return { a, b, segments };
});

for (let i = 0; i < turns * bpPerTurn * 10; i++) {
  const a = point(i / 10), b = point((i + 1) / 10);
  assert(b.x > a.x && a.y * b.z - a.z * b.y > 0, 'right-handed: positive x advance and counter-clockwise y/z twist');
}
assert(Math.abs(twist * 10.5 - 2 * Math.PI) < 1e-12, '10.5 bp per turn');
assert(Math.abs(offset - (2 * Math.PI - offset)) > .1, 'unequal major/minor grooves');
assert.equal(backbones.length, 2);
assert(rungs.length >= 30);
// Integer base pairs repeat after two turns (21 bp), not after a half-integer 10.5 bp.
const period = 2 * pitch;
assert(Math.abs(point(21).y - point(0).y) < 1e-12);
assert(Math.abs(point(21).z - point(0).z) < 1e-12);
writeFileSync(new URL('../src/components/helix-paths.json', import.meta.url), JSON.stringify({
  radius, rise, bpPerTurn, turns, offsetDegrees: 140, pitch, period, backbones, rungs,
}) + '\n');
console.log(`B-DNA self-check passed: right-handed, ${bpPerTurn} bp/turn, 140°/220° grooves, ${backbones.length} backbones, ${rungs.length} rungs, 21-bp seamless repeat`);
