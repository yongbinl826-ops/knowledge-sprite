import type { CapacitorConfig } from '@capacitor/cli';

// Only the explicit local preparation script sets this. Release preparation
// and the Gradle release gate both reject a debug-generated native config.
const debugLoopback = process.env.MOBILE_BUILD_KIND === 'debug';

const config: CapacitorConfig = {
  appId: 'dev.knowledgeguide.sprite',
  appName: '项目制学习引导小精灵',
  webDir: 'dist-mobile',
  server: {
    hostname: 'localhost',
    androidScheme: 'https',
    cleartext: false,
  },
  android: {
    allowMixedContent: debugLoopback,
    webContentsDebuggingEnabled: false,
  },
};

export default config;
