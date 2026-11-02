import {
  defineConfig,
  minimal2023Preset as preset,
} from "@vite-pwa/assets-generator/config";

// Generates the PWA icons in public/ from the logo mark:
//   npx pwa-assets-generator
// Padded icons (maskable, Apple) are filled with the accent blue, so launchers
// show a full blue tile with the white bars.
export default defineConfig({
  preset: {
    ...preset,
    maskable: {
      ...preset.maskable,
      resizeOptions: { background: "#2F6FEB" },
    },
    apple: {
      ...preset.apple,
      resizeOptions: { background: "#2F6FEB" },
    },
  },
  images: ["public/favicon.svg"],
});
