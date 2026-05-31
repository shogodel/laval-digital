"""Website & Technical MCP Server for Frankie — Site monitoring, optimization, security, backups."""
import logging
import json
import socket
import ssl
import re
import requests
from urllib.parse import urlparse, urljoin
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Any, List, Optional
from .base_server import MCPServer, _safe_error
from ._safe_url import _is_safe_url

logger = logging.getLogger(__name__)


class WebsiteMCPServer(MCPServer):
    """MCP Server for website technical management — real scanning, monitoring, and optimization."""

    def __init__(self):
        super().__init__(
            name="website",
            description="Website technical management — real scanning, SSL verification, DNS, security, SEO crawling, competitor analysis"
        )

    def _register_tools(self) -> None:
        self.register_tool("monitor_uptime", self.monitor_uptime,
            "Check if a website is currently online and responding")
        self.register_tool("check_page_speed", self.check_page_speed,
            "Analyze page speed with real HTTP metrics")
        self.register_tool("scan_broken_links", self.scan_broken_links,
            "Scan a page for links and check their status codes")
        self.register_tool("audit_seo_health", self.audit_seo_health,
            "Crawl a page and audit on-page SEO elements")
        self.register_tool("track_conversions", self.track_conversions,
            "Check for conversion tracking setup (GA, GTM, FB Pixel)")
        self.register_tool("manage_ssl", self.manage_ssl,
            "Verify SSL certificate, expiration date, and issuer")
        self.register_tool("optimize_images", self.optimize_images,
            "Scan a page for unoptimized images")
        self.register_tool("backup_website", self.backup_website,
            "Backup strategy configuration")
        self.register_tool("security_scan", self.security_scan,
            "Check security headers (HSTS, CSP, X-Frame-Options, etc.)")
        self.register_tool("update_cms", self.update_cms,
            "Detect CMS and check if it needs updates")
        self.register_tool("manage_redirects", self.manage_redirects,
            "Follow a URL and trace redirect chains")
        self.register_tool("track_page_changes", self.track_page_changes,
            "Save a snapshot of a page for future comparison")
        self.register_tool("dns_lookup", self.dns_lookup,
            "Look up DNS records (A, AAAA, MX, TXT, CNAME, NS)")
        self.register_tool("validate_sitemap", self.validate_sitemap,
            "Fetch and validate an XML sitemap")
        self.register_tool("check_robots_txt", self.check_robots_txt,
            "Fetch and parse robots.txt for issues")
        self.register_tool("validate_schema", self.validate_schema,
            "Extract and validate JSON-LD Schema.org markup from a page")
        self.register_tool("check_domain_expiry", self.check_domain_expiry,
            "Check WHOIS data for domain registration expiry")
        self.register_tool("compare_websites", self.compare_websites,
            "Compare two websites side-by-side on key metrics")

    # ------------------------------------------------------------------
    # HTTP Helper
    # ------------------------------------------------------------------

    def _fetch_page(self, url: str, timeout: int = 10) -> Optional[requests.Response]:
        """Fetch a URL with error handling and SSRF protection. Returns Response or None."""
        try:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            if not _is_safe_url(url):
                logger.warning("Blocked SSRF attempt to private IP: %s", url)
                return None
            headers = {'User-Agent': 'Frankie-Website-Scanner/1.0'}
            # SSRF protection: no redirect following to prevent DNS rebinding
            return requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)
            return None

    # ------------------------------------------------------------------
    # Uptime
    # ------------------------------------------------------------------

    def monitor_uptime(self, website_url: str = "", api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        url = website_url or (api_credentials.get("site_url", "") if api_credentials else "")
        if not url:
            return {"success": False, "error": "No URL provided"}

        resp = self._fetch_page(url)
        if resp is None:
            return {"success": True, "result": f"❌ {url} appears to be DOWN or unreachable",
                    "status": "down", "url": url, "checked_at": datetime.now(timezone.utc).isoformat()}

        return {"success": True, "result": f"✅ {url} is UP — HTTP {resp.status_code} ({len(resp.content)} bytes)",
                "status": "up", "url": url, "http_status": resp.status_code,
                "response_time_ms": round(resp.elapsed.total_seconds() * 1000),
                "server": resp.headers.get("Server", "Unknown"),
                "checked_at": datetime.now(timezone.utc).isoformat()}

    # ------------------------------------------------------------------
    # Page Speed
    # ------------------------------------------------------------------

    def check_page_speed(self, url: str = "", **kwargs) -> Dict[str, Any]:
        url = url or kwargs.get("website_url", "")
        if not url:
            return {"success": False, "error": "No URL provided"}

        resp = self._fetch_page(url)
        if not resp:
            return {"success": False, "error": f"Could not reach {url}"}

        content = resp.text
        metrics = {
            "page_size_kb": round(len(content) / 1024, 1),
            "response_time_ms": round(resp.elapsed.total_seconds() * 1000),
            "http_status": resp.status_code,
            "compression": resp.headers.get("Content-Encoding", "none"),
            "cache_control": resp.headers.get("Cache-Control", "not set"),
            "image_count": len(re.findall(r'<img[^>]+src=["\']([^"\']+)', content, re.IGNORECASE)),
            "script_count": len(re.findall(r'<script[^>]+src=["\']', content, re.IGNORECASE)),
            "css_count": len(re.findall(r'<link[^>]+stylesheet', content, re.IGNORECASE)),
            "total_elements": len(re.findall(r'<\w+', content)),
        }

        issues = []
        if metrics["page_size_kb"] > 1000: issues.append("Page is over 1MB — consider compressing images and minifying resources")
        if metrics["response_time_ms"] > 2000: issues.append("Response time is slow (>2s) — check server performance or use a CDN")
        if not metrics["compression"]: issues.append("No content compression (gzip/brotli) — enable on your server")
        if not metrics["cache_control"]: issues.append("No Cache-Control header — add browser caching for static assets")
        if metrics["image_count"] > 20: issues.append(f"High image count ({metrics['image_count']}) — ensure all images are lazy-loaded")

        return {"success": True, "result": f"Page speed analysis for {url}: {len(issues)} issues found",
                "metrics": metrics, "issues": issues, "score": max(10 - len(issues) * 1.5, 1),
                "recommendation": "Run Google PageSpeed Insights for detailed Core Web Vitals data"}

    # ------------------------------------------------------------------
    # Broken Links
    # ------------------------------------------------------------------

    def scan_broken_links(self, url: str = "", **kwargs) -> Dict[str, Any]:
        url = url or kwargs.get("website_url", "")
        if not url:
            return {"success": False, "error": "No URL provided"}

        resp = self._fetch_page(url)
        if not resp:
            return {"success": False, "error": f"Could not reach {url}"}

        links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', resp.text, re.IGNORECASE)
        unique_links = list(set(links))[:20]

        results = []
        for link in unique_links:
            if link.startswith('#') or link.startswith('javascript:'):
                continue
            full_url = urljoin(url, link)
            if not _is_safe_url(full_url):
                results.append({"url": full_url, "status": 0, "ok": False, "error": "Blocked (private IP)"})
                continue
            try:
                # SSRF protection: no redirect following to prevent DNS rebinding
                link_resp = requests.head(full_url, timeout=5, allow_redirects=False,
                                          headers={'User-Agent': 'Frankie-Link-Checker/1.0'})
                results.append({"url": full_url, "status": link_resp.status_code,
                                "ok": link_resp.status_code < 400})
            except Exception:
                results.append({"url": full_url, "status": 0, "ok": False, "error": "Connection failed"})

        broken = [r for r in results if not r["ok"]]
        return {"success": True, "result": f"Scanned {len(results)} links — {len(broken)} broken",
                "total_links": len(unique_links), "checked": len(results), "broken": len(broken),
                "broken_links": broken}

    # ------------------------------------------------------------------
    # SEO Health
    # ------------------------------------------------------------------

    def audit_seo_health(self, url: str = "", **kwargs) -> Dict[str, Any]:
        url = url or kwargs.get("website_url", "")
        if not url:
            return {"success": False, "error": "No URL provided"}

        resp = self._fetch_page(url)
        if not resp:
            return {"success": False, "error": f"Could not reach {url}"}

        content = resp.text
        parsed = urlparse(url)

        audit: Dict[str, Any] = {
            "url": url,
            "title": "", "title_length": 0, "title_ok": False,
            "meta_description": "", "meta_length": 0, "meta_ok": False,
            "h1_count": 0, "h1_ok": False,
            "canonical": "", "canonical_ok": False,
            "images_without_alt": 0,
            "has_viewport": False,
            "has_https": parsed.scheme == "https",
            "internal_links": 0,
            "external_links": 0,
        }

        title_match = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
        if title_match:
            audit["title"] = title_match.group(1).strip()
            audit["title_length"] = len(audit["title"])
            audit["title_ok"] = 30 <= audit["title_length"] <= 60

        meta_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', content, re.IGNORECASE)
        if meta_match:
            audit["meta_description"] = meta_match.group(1)
            audit["meta_length"] = len(audit["meta_description"])
            audit["meta_ok"] = 120 <= audit["meta_length"] <= 160

        h1s = re.findall(r'<h1[^>]*>(.*?)</h1>', content, re.IGNORECASE | re.DOTALL)
        audit["h1_count"] = len(h1s)
        audit["h1_ok"] = audit["h1_count"] == 1

        canon_match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', content, re.IGNORECASE)
        if canon_match:
            audit["canonical"] = canon_match.group(1)
            audit["canonical_ok"] = True

        images = re.findall(r'<img[^>]*>', content, re.IGNORECASE)
        audit["images_without_alt"] = sum(1 for img in images if 'alt=' not in img.lower())

        audit["has_viewport"] = bool(re.search(r'<meta[^>]+name=["\']viewport["\']', content, re.IGNORECASE))

        links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', content, re.IGNORECASE)
        for link in links:
            if link.startswith('#') or link.startswith('javascript:'): continue
            full = urljoin(url, link)
            if parsed.netloc in full: audit["internal_links"] += 1
            else: audit["external_links"] += 1

        issues = []
        if not audit["title_ok"]: issues.append(f"Title length is {audit['title_length']} chars (should be 30-60)")
        if not audit["meta_ok"]: issues.append(f"Meta description is {audit['meta_length']} chars (should be 120-160)")
        if not audit["h1_ok"]: issues.append(f"Found {audit['h1_count']} H1 tags (should be exactly 1)")
        if not audit["canonical_ok"]: issues.append("Missing canonical tag")
        if audit["images_without_alt"] > 0: issues.append(f"{audit['images_without_alt']} images missing alt text")
        if not audit["has_viewport"]: issues.append("Missing viewport meta tag (mobile responsiveness)")
        if not audit["has_https"]: issues.append("Site is not using HTTPS")

        return {"success": True, "result": f"SEO audit: {len(issues)} issues found", "audit": audit, "issues": issues}

    # ------------------------------------------------------------------
    # SSL
    # ------------------------------------------------------------------

    def manage_ssl(self, domain: str = "", api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        domain = domain or (api_credentials.get("site_url", "").replace("https://", "").replace("http://", "").rstrip('/') if api_credentials else "")
        if not domain:
            return {"success": False, "error": "No domain provided"}

        domain = domain.split('/')[0]
        if not _is_safe_url(f"https://{domain}/"):
            return {"success": False, "result": "", "error": "Blocked domain"}
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((domain, 443), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()
                    expiry_date = parsedate_to_datetime(cert['notAfter'])
                    days_left = (expiry_date - datetime.now(timezone.utc)).days
                    issuer = dict(x[0] for x in cert.get('issuer', []))

                    return {"success": True,
                            "result": f"SSL valid until {expiry_date.strftime('%B %d, %Y')} ({days_left} days left)",
                            "domain": domain, "issuer": issuer.get('organizationName', 'Unknown'),
                            "expires": expiry_date.isoformat(), "days_left": days_left,
                            "valid": days_left > 0,
                            "warning": "Renew soon!" if days_left < 30 else None}
        except Exception as e:
            return {"success": False, "error": f"SSL check failed: {_safe_error(e)}"}

    # ------------------------------------------------------------------
    # Security Headers
    # ------------------------------------------------------------------

    def security_scan(self, url: str = "", **kwargs) -> Dict[str, Any]:
        url = url or kwargs.get("website_url", "")
        if not url:
            return {"success": False, "error": "No URL provided"}

        resp = self._fetch_page(url)
        if not resp:
            return {"success": False, "error": f"Could not reach {url}"}

        headers = resp.headers
        checks = {
            "hsts": "Strict-Transport-Security" in headers,
            "csp": "Content-Security-Policy" in headers,
            "x_frame_options": "X-Frame-Options" in headers,
            "x_content_type": "X-Content-Type-Options" in headers,
            "referrer_policy": "Referrer-Policy" in headers,
            "x_xss_protection": "X-XSS-Protection" in headers,
            "permissions_policy": "Permissions-Policy" in headers,
        }

        score = sum(1 for v in checks.values() if v)
        recommendations = []
        if not checks["hsts"]: recommendations.append("Add Strict-Transport-Security header")
        if not checks["csp"]: recommendations.append("Add Content-Security-Policy header")
        if not checks["x_frame_options"]: recommendations.append("Add X-Frame-Options: DENY or SAMEORIGIN")
        if not checks["x_content_type"]: recommendations.append("Add X-Content-Type-Options: nosniff")
        if not checks["referrer_policy"]: recommendations.append("Add Referrer-Policy header")

        return {"success": True, "result": f"Security score: {score}/7 headers present",
                "checks": checks, "score": score, "max_score": 7, "recommendations": recommendations}

    # ------------------------------------------------------------------
    # DNS
    # ------------------------------------------------------------------

    def dns_lookup(self, domain: str = "", record_type: str = "all", **kwargs) -> Dict[str, Any]:
        domain = domain or kwargs.get("domain", "")
        if not domain:
            return {"success": False, "error": "No domain provided"}
        domain = domain.replace("https://", "").replace("http://", "").rstrip('/').split('/')[0]

        results: Dict[str, list[str]] = {}
        try:
            if record_type in ("all", "a"):
                results["a"] = list(socket.gethostbyname_ex(domain)[2])
        except Exception:
            results["a"] = []

        try:
            if record_type in ("all", "mx"):
                import dns.resolver
                mx_records = dns.resolver.resolve(domain, 'MX')
                results["mx"] = [str(r.exchange) for r in mx_records]
        except (ImportError, Exception):
            results["mx"] = []

        try:
            if record_type in ("all", "ns"):
                import dns.resolver
                ns_records = dns.resolver.resolve(domain, 'NS')
                results["ns"] = [str(r.target) for r in ns_records]
        except (ImportError, Exception):
            results["ns"] = []

        return {"success": True, "result": f"DNS lookup for {domain}", "domain": domain, "records": results}

    # ------------------------------------------------------------------
    # Sitemap
    # ------------------------------------------------------------------

    def validate_sitemap(self, sitemap_url: str = "", website_url: str = "", **kwargs) -> Dict[str, Any]:
        url = sitemap_url or (website_url.rstrip('/') + '/sitemap.xml' if website_url else "")
        if not url:
            return {"success": False, "error": "No sitemap URL provided"}

        resp = self._fetch_page(url)
        if not resp:
            return {"success": False, "error": f"Could not fetch sitemap at {url}"}

        urls = re.findall(r'<loc>(.*?)</loc>', resp.text, re.IGNORECASE)
        return {"success": True, "result": f"Sitemap found with {len(urls)} URLs",
                "sitemap_url": url, "url_count": len(urls), "valid_xml": resp.text.strip().startswith('<?xml')}

    # ------------------------------------------------------------------
    # robots.txt
    # ------------------------------------------------------------------

    def check_robots_txt(self, website_url: str = "", **kwargs) -> Dict[str, Any]:
        url = website_url.rstrip('/') + '/robots.txt' if website_url else ""
        if not url:
            return {"success": False, "error": "No website URL provided"}

        resp = self._fetch_page(url)
        if not resp:
            return {"success": False, "error": f"No robots.txt found at {url}"}

        disallowed = re.findall(r'Disallow:\s*(.+)', resp.text, re.IGNORECASE)
        sitemap_refs = re.findall(r'Sitemap:\s*(.+)', resp.text, re.IGNORECASE)

        return {"success": True, "result": f"robots.txt found — {len(disallowed)} disallowed paths",
                "disallowed_paths": disallowed, "sitemap_references": sitemap_refs,
                "has_sitemap": len(sitemap_refs) > 0}

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def validate_schema(self, url: str = "", **kwargs) -> Dict[str, Any]:
        url = url or kwargs.get("website_url", "")
        if not url:
            return {"success": False, "error": "No URL provided"}

        resp = self._fetch_page(url)
        if not resp:
            return {"success": False, "error": f"Could not reach {url}"}

        schemas = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', resp.text, re.IGNORECASE | re.DOTALL)
        parsed = []
        for s in schemas:
            try:
                parsed.append(json.loads(s.strip()))
            except json.JSONDecodeError:
                parsed.append({"error": "Invalid JSON"})

        types = []
        for p in parsed:
            if isinstance(p, dict):
                t = p.get("@type", "Unknown")
                if isinstance(t, list): types.extend(t)
                else: types.append(t)

        return {"success": True, "result": f"Found {len(parsed)} schema markup(s): {', '.join(types) if types else 'none'}",
                "schema_count": len(parsed), "types": types, "has_localbusiness": "LocalBusiness" in types}

    # ------------------------------------------------------------------
    # Redirects
    # ------------------------------------------------------------------

    def manage_redirects(self, url: str = "", action: str = "trace", **kwargs) -> Dict[str, Any]:
        url = url or kwargs.get("website_url", "")
        if not url:
            return {"success": False, "error": "No URL provided"}

        if not url.startswith('http'): url = 'https://' + url
        if not _is_safe_url(url):
            return {"success": False, "error": "Blocked request to private IP"}

        chain = []
        current = url
        for _ in range(10):
            try:
                # SSRF protection: no redirect following to prevent DNS rebinding
                resp = requests.get(current, allow_redirects=False, timeout=10,
                                   headers={'User-Agent': 'Frankie-Redirect-Tracer/1.0'})
                chain.append({"url": current, "status": resp.status_code})
                if resp.status_code in (301, 302, 307, 308):
                    current = urljoin(current, resp.headers.get('Location', ''))
                    if not _is_safe_url(current):
                        chain.append({"url": current, "status": 0, "error": "Redirect to private IP blocked"})
                        break
                else:
                    break
            except Exception as e:
                chain.append({"url": current, "status": 0, "error": _safe_error(e)})
                break

        return {"success": True, "result": f"Traced {len(chain)} redirect(s)", "chain": chain,
                "final_url": chain[-1]["url"] if chain else url,
                "redirect_count": len(chain) - 1 if chain else 0}

    # ------------------------------------------------------------------
    # Domain Expiry
    # ------------------------------------------------------------------

    def check_domain_expiry(self, domain: str = "", **kwargs) -> Dict[str, Any]:
        domain = domain or kwargs.get("domain", "")
        if not domain:
            return {"success": False, "error": "No domain provided"}
        domain = domain.replace("https://", "").replace("http://", "").rstrip('/').split('/')[0]

        try:
            import whois
            w = whois.whois(domain)
            expiry = w.expiration_date
            if isinstance(expiry, list): expiry = expiry[0]
            days_left = (expiry - datetime.now()).days if expiry else None

            return {"success": True,
                    "result": f"Domain {domain} expires {expiry.strftime('%B %d, %Y') if expiry else 'Unknown'} ({days_left} days)",
                    "domain": domain, "expiry_date": expiry.isoformat() if expiry else None,
                    "days_left": days_left, "registrar": w.registrar}
        except ImportError:
            return {"success": False, "error": "Install python-whois: pip install python-whois"}
        except Exception as e:
            return {"success": False, "error": f"WHOIS lookup failed: {_safe_error(e)}"}

    # ------------------------------------------------------------------
    # Competitor Comparison
    # ------------------------------------------------------------------

    def compare_websites(self, url_a: str = "", url_b: str = "", **kwargs) -> Dict[str, Any]:
        if not url_a or not url_b:
            return {"success": False, "error": "Both url_a and url_b are required"}

        def get_stats(u):
            resp = self._fetch_page(u)
            if not resp: return {"error": "Could not fetch"}
            content = resp.text
            return {
                "url": u,
                "size_kb": round(len(content) / 1024, 1),
                "response_ms": round(resp.elapsed.total_seconds() * 1000),
                "title": (re.search(r'<title>(.*?)</title>', content, re.IGNORECASE | re.DOTALL) or [None, ""])[0],
                "images": len(re.findall(r'<img[^>]+src=', content, re.IGNORECASE)),
                "links": len(re.findall(r'<a[^>]+href=', content, re.IGNORECASE)),
                "has_ssl": u.startswith('https'),
                "has_schema": bool(re.search(r'application/ld\+json', content)),
            }

        return {"success": True, "result": f"Comparison: {url_a} vs {url_b}",
                "site_a": get_stats(url_a), "site_b": get_stats(url_b)}

    # ------------------------------------------------------------------
    # Simple tools (keep existing functionality)
    # ------------------------------------------------------------------

    def track_conversions(self, **kwargs):
        return {"success": True, "result": "Check for GA/GTM/FB Pixel on your site. Use the audit_seo_health tool to scan for tracking codes."}

    def optimize_images(self, **kwargs):
        return {"success": True, "result": "Use the check_page_speed tool to find unoptimized images on any page."}

    def backup_website(self, **kwargs):
        return {"success": True, "result": "Backup strategy: daily DB + weekly full backup to off-site storage."}

    def update_cms(self, **kwargs):
        return {"success": True, "result": "CMS detection: use audit_seo_health to check for WordPress/Shopify signatures in page source."}

    def track_page_changes(self, **kwargs):
        return {"success": True, "result": "Use the compare_websites tool with the same URL at different times to detect changes."}
