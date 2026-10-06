import type { MetadataRoute } from "next";
import { siteUrl as siteUrl_ } from "@/lib/config.server";

const siteUrl = siteUrl_();

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
