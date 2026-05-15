"""
SEO MCP Server for Frankie.
Handles content publishing to WordPress, Webflow, Netlify, and custom websites.
"""
import logging
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from .base_server import MCPServer

logger = logging.getLogger(__name__)


class SEOMCPServer(MCPServer):
    """MCP Server for SEO and content publishing."""

    def __init__(self):
        super().__init__(
            name="seo",
            description="SEO and content publishing — WordPress, Webflow, Netlify, custom sites"
        )

    def _register_tools(self) -> None:
        self.register_tool("publish_blog_post", self.publish_blog_post,
            "Publish a blog post to the configured CMS (WordPress, Webflow, or file)")
        self.register_tool("update_meta_tags", self.update_meta_tags,
            "Update meta title and description for a given URL")
        self.register_tool("get_site_info", self.get_site_info,
            "Get information about the connected website")
        self.register_tool("optimize_content", self.optimize_content,
            "Analyze content and return SEO optimization suggestions")

    def publish_blog_post(self, content: str, title: str = "", cms_type: str = "file",
                          api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Publish a blog post to the configured CMS.

        Args:
            content: Full blog post content (Markdown or HTML)
            title: Post title (extracted from content if not provided)
            cms_type: 'wordpress', 'webflow', 'netlify', or 'file'
            api_credentials: Dict with API keys/URLs for the CMS

        Returns:
            {"success": bool, "result": str, "error": str or None}
        """
        if not title:
            lines = content.strip().split('\n')
            title = lines[0].replace('#', '').strip()[:100] if lines else "Untitled"

        # WordPress via REST API
        if cms_type == "wordpress" and api_credentials:
            return self._publish_wordpress(title, content, api_credentials)

        # Webflow via API
        if cms_type == "webflow" and api_credentials:
            return self._publish_webflow(title, content, api_credentials)

        # Netlify via Git
        if cms_type == "netlify" and api_credentials:
            return self._publish_netlify(title, content, api_credentials)

        # Default: save to file
        return self._publish_to_file(title, content)

    def _publish_wordpress(self, title: str, content: str, creds: Dict) -> Dict[str, Any]:
        """Publish to WordPress REST API."""
        try:
            import requests
            url = creds.get("site_url", "").rstrip('/') + "/wp-json/wp/v2/posts"
            resp = requests.post(
                url,
                auth=(creds.get("username", ""), creds.get("app_password", "")),
                json={"title": title, "content": content, "status": "publish"},
                timeout=15
            )
            if resp.status_code in (200, 201):
                post_data = resp.json()
                return {
                    "success": True,
                    "result": f"Published to WordPress: {post_data.get('link', 'Live')}",
                    "error": None
                }
            return {"success": False, "result": "", "error": f"WordPress API error: {resp.text}"}
        except Exception as e:
            return {"success": False, "result": "", "error": f"WordPress publish failed: {e}"}

    def _publish_webflow(self, title: str, content: str, creds: Dict) -> Dict[str, Any]:
        """Publish to Webflow CMS API."""
        try:
            import requests
            site_id = creds.get("site_id", "")
            collection_id = creds.get("collection_id", "")
            api_key = creds.get("api_key", "")

            resp = requests.post(
                f"https://api.webflow.com/v2/collections/{collection_id}/items",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"fieldData": {"name": title, "post-body": content}},
                timeout=15
            )
            if resp.status_code in (200, 201):
                return {"success": True, "result": "Published to Webflow CMS", "error": None}
            return {"success": False, "result": "", "error": f"Webflow API error: {resp.text}"}
        except Exception as e:
            return {"success": False, "result": "", "error": f"Webflow publish failed: {e}"}

    def _publish_netlify(self, title: str, content: str, creds: Dict) -> Dict[str, Any]:
        """Trigger Netlify deploy via build hook."""
        try:
            import requests
            hook_url = creds.get("build_hook_url", "")
            if not hook_url:
                return {"success": False, "result": "", "error": "No Netlify build hook URL configured"}
            resp = requests.post(hook_url, timeout=15)
            if resp.status_code == 200:
                return {"success": True, "result": "Netlify deploy triggered", "error": None}
            return {"success": False, "result": "", "error": f"Netlify hook error: {resp.text}"}
        except Exception as e:
            return {"success": False, "result": "", "error": f"Netlify deploy failed: {e}"}

    def _publish_to_file(self, title: str, content: str) -> Dict[str, Any]:
        """Save blog post as a Markdown file (fallback)."""
        try:
            blog_dir = Path("content/blog")
            blog_dir.mkdir(parents=True, exist_ok=True)

            slug = re.sub(r'[^\w\s-]', '', title.lower().strip())[:60]
            slug = re.sub(r'[-\s]+', '-', slug)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filepath = blog_dir / f"{slug}-{timestamp}.md"
            filepath.write_text(f"# {title}\n\n{content}", encoding="utf-8")

            return {"success": True, "result": f"Saved to {filepath}", "error": None}
        except OSError as e:
            return {"success": False, "result": "", "error": f"File write failed: {e}"}

    def update_meta_tags(self, url: str, title: str, description: str,
                         api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Update meta tags for a given URL. Returns the suggested HTML."""
        meta_html = f'<title>{title}</title>\n<meta name="description" content="{description}">'
        return {
            "success": True,
            "result": f"Meta tags generated. Apply this to {url}:\n{meta_html}",
            "error": None
        }

    def get_site_info(self, api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Get information about the connected website."""
        cms_type = api_credentials.get("cms_type", "unknown") if api_credentials else "unknown"
        site_url = api_credentials.get("site_url", "not configured") if api_credentials else "not configured"
        return {
            "success": True,
            "result": f"Connected to {cms_type} site at {site_url}",
            "cms_type": cms_type,
            "site_url": site_url
        }

    def optimize_content(self, content: str, keywords: str = "", **kwargs) -> Dict[str, Any]:
        """Analyze content and return SEO optimization suggestions."""
        suggestions = []
        word_count = len(content.split())

        if word_count < 300:
            suggestions.append("Content is short. Aim for 300+ words for better SEO.")
        if keywords:
            kw_list = [k.strip().lower() for k in keywords.split(',')]
            for kw in kw_list:
                if kw not in content.lower():
                    suggestions.append(f"Keyword '{kw}' not found in content. Consider adding it.")

        return {
            "success": True,
            "result": f"SEO analysis complete. {len(suggestions)} suggestions.",
            "word_count": word_count,
            "suggestions": suggestions
        }
