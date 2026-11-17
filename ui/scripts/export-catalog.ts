/** Writes the navigator A2UI catalog definition (basic v1.0 + navigator components) as JSON.
 *  Usage: npm run catalog:export  ->  ../api/a2ui/navigator_catalog.json */
import './dom';
import {writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const {navigatorCatalog, NAVIGATOR_COMPONENTS} = await import('../src/a2ui/catalog');
const doc = navigatorCatalog.toJson() as Record<string, unknown>;
doc.title = 'Stabilization Navigator catalog';
doc.description =
  'A2UI v1.0 basic catalog plus the Tenant Stabilization Navigator components (' +
  NAVIGATOR_COMPONENTS.map(c => c.name).join(', ') + '). Implemented by ui/src/a2ui/catalog.tsx.';
const out = fileURLToPath(new URL('../../api/a2ui/navigator_catalog.json', import.meta.url));
writeFileSync(out, JSON.stringify(doc, null, 2) + '\n');
console.log(`wrote ${out} (${Object.keys(doc.components as object).length} components)`);
