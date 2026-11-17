/**
 * Feeds A2UI messages produced by the API through the real A2UI renderer core
 * (@a2ui/web_core MessageProcessor) with the navigator catalog, and fails on any error.
 *
 *   python -m pytest api/tests -q        # writes api/tests/out/a2ui_messages.json
 *   npm run validate:a2ui                # (from ui/) validates them
 */
import './dom';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const {MessageProcessor} = await import('@a2ui/web_core');
const {navigatorCatalog} = await import('../src/a2ui/catalog');

const file = process.argv[2] ?? fileURLToPath(new URL('../../api/tests/out/a2ui_messages.json', import.meta.url));
const messages = JSON.parse(readFileSync(file, 'utf8')) as unknown[];
const errors: unknown[] = [];
const p = new MessageProcessor([navigatorCatalog as never], undefined, {
  version: '1.0' as never,
  reportErrorsOnly: true,
  errorHandler: e => errors.push(e),
});
let i = 0;
for (const m of messages) {
  const errs = p.processMessagesWithErrors([m]);
  if (errs.length) errors.push({index: i, message: JSON.stringify(m).slice(0, 200), errs});
  i++;
}
const surfaces = [...p.model.surfacesMap.keys()];
console.log(`processed ${messages.length} messages · surfaces: ${surfaces.join(', ')}`);
if (errors.length) {
  console.error(JSON.stringify(errors.slice(0, 10), null, 2));
  console.error(`${errors.length} A2UI error(s)`);
  process.exit(1);
}
console.log('A2UI messages valid against the navigator catalog ✓');
