import type { MetadataRoute } from "next";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Account and demo-data surfaces stay out of search results.
      disallow: ["/login", "/signup", "/forgot-password", "/verify-phone", "/verify-email", "/dashboard", "/api/"],
    },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
