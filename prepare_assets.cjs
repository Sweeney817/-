// Pack the generated artwork into exact cells; keep character artwork unchanged.
const fs = require('node:fs');
const path = require('node:path');
const modules = process.env.CODEX_NODE_MODULES || 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const sharp = require(path.join(modules, 'sharp'));
const { PNG } = require(path.join(modules, 'pngjs'));
const assets = path.join(__dirname, 'assets');

async function main() {
  const source = PNG.sync.read(fs.readFileSync(path.join(assets, 'liuliu-source.png')));
  const { width, height, data } = source;
  const bands = [];
  let start = null;
  for (let y = 0; y < height; y++) {
    let active = false;
    for (let x = 0; x < width; x++) {
      if (data[(y * width + x) * 4 + 3] >= 72) { active = true; break; }
    }
    if (active && start === null) start = y;
    if (!active && start !== null) { bands.push([start, y]); start = null; }
  }
  if (start !== null) bands.push([start, height]);
  if (bands.length !== 8) throw new Error(`Expected 8 action rows, found ${bands.length}`);
  const layers = [];
  const report = [];
  for (let row = 0; row < bands.length; row++) {
    const [top, bottom] = bands[row];
    const density = Array(width).fill(0);
    for (let x = 0; x < width; x++) for (let y = top; y < bottom; y++) {
      if (data[(y * width + x) * 4 + 3] >= 72) density[x]++;
    }
    const cuts = [0];
    for (let col = 1; col < 4; col++) {
      const expected = Math.round(col * width / 4);
      let best = expected;
      for (let x = expected - 16; x <= expected + 16; x++) {
        if (density[x] < density[best]) best = x;
      }
      cuts.push(best);
    }
    cuts.push(width);
    const boxes = [];
    for (let col = 0; col < 4; col++) {
      let x0 = width, y0 = height, x1 = 0, y1 = 0;
      for (let y = top; y < bottom; y++) for (let x = cuts[col]; x < cuts[col + 1]; x++) {
        if (data[(y * width + x) * 4 + 3] < 72) continue;
        x0 = Math.min(x0, x); x1 = Math.max(x1, x);
        y0 = Math.min(y0, y); y1 = Math.max(y1, y);
      }
      if (x1 <= x0 || y1 <= y0) throw new Error(`Empty frame ${row}:${col}`);
      boxes.push({left:x0, top:y0, width:x1-x0+1, height:y1-y0+1});
    }
    const scale = Math.min(176 / Math.max(...boxes.map(b => b.width)), 190 / Math.max(...boxes.map(b => b.height)));
    for (let col = 0; col < 4; col++) {
      const box = boxes[col];
      const w = Math.round(box.width * scale), h = Math.round(box.height * scale);
      const input = await sharp(path.join(assets, 'liuliu-source.png')).extract(box).resize(w,h).png().toBuffer();
      layers.push({input, left: col * 192 + Math.round((192-w)/2), top: row * 208 + 200-h});
    }
    report.push({row, cuts, cutsAlpha:cuts.slice(1,-1).map(x=>density[x]), boxes, scale});
  }
  await sharp({create:{width:768,height:1664,channels:4,background:{r:0,g:0,b:0,alpha:0}}})
    .composite(layers).png().toFile(path.join(assets,'spritesheet.png'));
  // A PNG-backed ICO preserves the generated alpha and supports Explorer icons.
  const icon = await sharp(path.join(assets,'spritesheet.png')).extract({left:0,top:0,width:192,height:208})
    .resize(256,256,{fit:'contain',background:{r:0,g:0,b:0,alpha:0}}).png().toBuffer();
  const header = Buffer.alloc(22);
  header.writeUInt16LE(1,2); header.writeUInt16LE(1,4);
  header.writeUInt16LE(1,10); header.writeUInt16LE(32,12);
  header.writeUInt32LE(icon.length,14); header.writeUInt32LE(22,18);
  fs.writeFileSync(path.join(assets,'orange-cat.ico'), Buffer.concat([header,icon]));
  fs.writeFileSync(path.join(assets,'packing-report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report.map(r=>({row:r.row,cutsAlpha:r.cutsAlpha})),null,2));
}
main().catch(error => { console.error(error); process.exit(1); });
