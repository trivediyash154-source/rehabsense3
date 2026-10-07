import type { MetadataRoute } from "next";
import { siteUrl as siteUrl_ } from "@/lib/config.server";

const siteUrl = siteUrl_();

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: siteUrl, changeFrequency: "monthly", priority: 1 },
    { url: `${siteUrl}/contact`, changeFrequency: "monthly", priority: 0.7 },
    { url: `${siteUrl}/cookies`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${siteUrl}/privacy`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${siteUrl}/data-deletion`, changeFrequency: "yearly", priority: 0.3 },
  ];
}
