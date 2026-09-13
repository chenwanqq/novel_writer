import { test } from 'node:test';
import assert from 'node:assert/strict';
import { viewPoint, scaledPoint, escapeXML } from '../src/geometry.mjs';

test('pointer coordinates account for pan and zoom', () => {
  assert.deepEqual(viewPoint(300, 200, {left: 100, top: 100, width: 400, height: 200},
    {x: -200, y: -100, w: 800, h: 400}), [200, 100]);
});
test('background replacement scales independent axes and preserves negative points', () => {
  assert.deepEqual(scaledPoint([-10, 50], [100, 100], [200, 50]), [-20, 25]);
  assert.equal(escapeXML('<script>&"'), '&lt;script&gt;&amp;&quot;');
});
