const fs = require('fs');

const htmlPath = 'E:\\SLAHAND\\mmhand_wrist_control_1.0\\徐钰公式推导\\2026-10-22\\腕部公式_可视化沙盘.html';
const clientPath = 'E:\\SLAHAND\\mmhand_wrist_control_1.0\\徐钰公式推导\\2026-10-22\\dsh-plugin-formula-panel\\client.js';

let html = fs.readFileSync(htmlPath, 'utf8');
if (html.charCodeAt(0) === 0xfeff) html = html.slice(1);

const match = /<script[^>]*>([\s\S]*?)<\/script>/.exec(html);
if (!match) throw new Error('script block not found');
const lines = match[1].split('\n');

const dataStart = lines.findIndex((l) => l.indexOf('var DEG = Math.PI/180;') >= 0);
const sceneBanner = lines.findIndex((l) => l.indexOf('================= 场景渲染 =================') >= 0);
if (dataStart < 0 || sceneBanner < 0) throw new Error('data block markers not found');
const dataBlock = lines.slice(dataStart, sceneBanner).join('\n');

function takeFn(name) {
  const start = lines.findIndex((l) => l.indexOf('  function ' + name + '(') === 0);
  if (start < 0) throw new Error('function not found: ' + name);
  let end = start;
  while (end < lines.length && lines[end] !== '  }') end += 1;
  if (end >= lines.length) throw new Error('function not closed: ' + name);
  return lines.slice(start, end + 1).join('\n');
}

const fnNames = [
  'fitScene', 'basis', 'resizeScene', 'project', 'updateOffset',
  'hull2d', 'cross2', 'line', 'label', 'arrowHead',
  'drawAxes', 'drawBodies', 'tagHull', 'drawRope', 'drawArcs',
  'drawFloor', 'renderScene',
];

let body = [dataBlock].concat(fnNames.map(takeFn)).join('\n\n');

body = body
  .replace(/\bctx\./g, 'g.')
  .replace(/\bcanvas\./g, 'cv.')
  .replace(/\bscene\./g, 'st.')
  .replace('var g = g.createRadialGradient', 'var glow = g.createRadialGradient')
  .replace(/g\.addColorStop/g, 'glow.addColorStop')
  .replace('g.fillStyle = g;', 'g.fillStyle = glow;');

body = body
  .split('\n')
  .map((l) => (l.length ? '      ' + l : l))
  .join('\n');

const block = `    /* ==== WRIST3D:BEGIN — 3D 场景移植自 腕部公式_可视化沙盘.html（canvas 2D，零依赖） ==== */
    function createWristView(cv) {
      var g = cv.getContext('2d');
      var st = {
        w: 0, h: 0, dpr: 1,
        tr: 0, tp: 0,
        azBase: 0.62, elBase: 0.30,
        azUser: 0, elUser: 0,
        t: 0,
        scale: 1, center: [0, 0, 0], span: 1,
        min: [0, 0, 0], max: [0, 0, 0],
        offx: 0, offy: 0,
      };

${body}

      fitScene();

      /** R(2×3) 与 f = 10 N 下的关节力矩，单位 mm/rad、N·mm。 */
      function readout(tr, tp) {
        var R = [[], []];
        for (var i = 0; i < 3; i++) {
          R[0].push(arm(tr, CABLES[i].rl));
          R[1].push(arm(tp, CABLES[i].pt));
        }
        var f = 10;
        return {
          R: R,
          tau: [R[0][0] * f + R[0][1] * f + R[0][2] * f, R[1][0] * f + R[1][1] * f + R[1][2] * f],
          lengths: CABLES.map(function (cab) {
            var geo = geoLen(cab, tr, tp);
            var closed = closedLen(cab, tr, tp);
            return { name: cab.name, geo: geo, closed: closed, diff: geo - closed };
          }),
        };
      }

      return {
        state: st,
        resize: function () {
          resizeScene();
          renderScene();
        },
        render: renderScene,
        readout: readout,
      };
    }
    /* ==== WRIST3D:END ==== */

`;

let client = fs.readFileSync(clientPath, 'utf8');
const start = client.indexOf('    /* ==== WRIST3D:BEGIN');
const end = client.indexOf('    /* ==== WRIST3D:END ==== */');
if (start < 0 || end < 0) throw new Error('existing block not found');
client = client.slice(0, start) + block + client.slice(end + '    /* ==== WRIST3D:END ==== */\n\n'.length);
fs.writeFileSync(clientPath, client, 'utf8');

console.log('block', block.length, 'chars; has mojibake:', /鑳屾櫙|鍏夋檿/.test(block));
console.log('client', client.length, 'chars');
