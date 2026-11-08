const assert = require('node:assert/strict');
const {test} = require('node:test');
const tools = require('../../inspinia/static/js/ranking-table-tools.js');

test('numeric sorting keeps zero, fractional values and missing values in the correct order', () => {
  const records = [10, null, 2, 0, 2.5].map((value, index) => ({index, keys: [value]}));
  assert.deepEqual(tools.orderRows(records, 0, 'asc').map(row => row.keys[0]), [0, 2, 2.5, 10, null]);
  assert.deepEqual(tools.orderRows(records, 0, 'desc').map(row => row.keys[0]), [10, 2.5, 2, 0, null]);
});

test('score sorting preserves stable tied ranks and never changes the source row objects', () => {
  const records = [
    {index: 0, keys: [34], rank: 2, student: 'B'},
    {index: 1, keys: [36], rank: 1, student: 'A'},
    {index: 2, keys: [34], rank: 2, student: 'C'},
  ];
  const ordered = tools.orderRows(records, 0, 'desc');
  assert.deepEqual(ordered.map(row => row.student), ['A', 'B', 'C']);
  assert.deepEqual(ordered.map(row => row.rank), [1, 2, 2]);
  assert.deepEqual(records.map(row => row.student), ['B', 'A', 'C']);
});

test('history columns sort scores before group labels and keep empty results last', () => {
  const records = ['GOLD PIONEER', 12, null, 2, 'BRONZE'].map((value, index) => ({index, keys: [value]}));
  assert.deepEqual(tools.orderRows(records, 0, 'asc').map(row => row.keys[0]), [2, 12, 'BRONZE', 'GOLD PIONEER', null]);
  assert.deepEqual(tools.orderRows(records, 0, 'desc').map(row => row.keys[0]), [12, 2, 'GOLD PIONEER', 'BRONZE', null]);
});

test('local filtering handles case, Unicode, words across cells and literal special characters', () => {
  const search = tools.normalize('Ａｌｅｘ  Pioneer\nSource notes: School [A]');
  assert.ok(tools.matches(search, 'alex school'));
  assert.ok(tools.matches(search, '[a]'));
  assert.ok(tools.matches(search, '  '));
  assert.ok(!tools.matches(search, '.*'));
  assert.ok(!tools.matches(search, 'alex beginner'));
});

test('copy uses the filtered sort order with headers and safely escapes spreadsheet formulas', () => {
  const records = [
    {index: 0, search: 'school a', keys: [2], values: ['Student A', 'School A', '2']},
    {index: 1, search: 'school b', keys: [10], values: ['Student B', 'School B', '10']},
    {index: 2, search: 'school a', keys: [0], values: ['=HYPERLINK("bad")', 'School A', '0']},
  ];
  const visible = tools.orderRows(records, 0, 'asc').filter(row => tools.matches(row.search, 'school a'));
  assert.equal(tools.toTSV(['Student', 'School', 'Score'], visible.map(row => row.values)),
    'Student\tSchool\tScore\n\'=HYPERLINK("bad")\tSchool A\t0\nStudent A\tSchool A\t2');
  assert.equal(tools.toTSV(['Value'], [['+SUM(1,2)'], ['@value'], ['-text'], ['-2.5'], ['line\twith\nspaces']]),
    "Value\n'+SUM(1,2)\n'@value\n'-text\n-2.5\nline with spaces");
});
