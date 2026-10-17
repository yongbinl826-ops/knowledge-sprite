import { defineConfig } from '../../../frontend/node_modules/vite/dist/node/index.js';
import react from '../../../frontend/node_modules/@vitejs/plugin-react/dist/index.js';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../../frontend/package.json', import.meta.url));
export default defineConfig({ base: './', plugins: [react()], resolve: { alias: {
  'react-dom/client': require.resolve('react-dom/client'),
  'react/jsx-runtime': require.resolve('react/jsx-runtime'),
  react: require.resolve('react'),
} } });
