import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://trendbio.dev",
  output: "static",
  integrations: [
    {
      name: "korean-development-preview",
      hooks: {
        "astro:server:setup": ({ server }) => {
          server.middlewares.use((request, response, next) => {
            if (!/^\/ko(?:[/?]|$)/.test(request.url ?? "")) return next();
            server.ssrLoadModule("/scripts/korean-preview.mjs")
              .then(({ koreanPreview }) => koreanPreview(request, response, next))
              .catch(next);
          });
        },
      },
    },
  ],
});
