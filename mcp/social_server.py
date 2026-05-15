"""
Social Media MCP Server for Frankie.
Handles posting to Facebook, Instagram, TikTok, and LinkedIn.
"""
import logging
import json
from pathlib import Path
from typing import Dict, Any
from .base_server import MCPServer

logger = logging.getLogger(__name__)


class SocialMCPServer(MCPServer):
    """MCP Server for social media posting."""

    def __init__(self):
        super().__init__(
            name="social",
            description="Social media posting — Facebook, Instagram, TikTok, LinkedIn"
        )

    def _register_tools(self) -> None:
        self.register_tool("post_to_facebook", self.post_to_facebook,
            "Publish a post to a Facebook Page")
        self.register_tool("post_to_instagram", self.post_to_instagram,
            "Publish a post to Instagram")
        self.register_tool("post_to_tiktok", self.post_to_tiktok,
            "Publish a video or post to TikTok")
        self.register_tool("post_to_linkedin", self.post_to_linkedin,
            "Publish a post to LinkedIn")
        self.register_tool("schedule_post", self.schedule_post,
            "Schedule a post for future publishing")
        self.register_tool("get_social_stats", self.get_social_stats,
            "Get basic engagement stats")

    def post_to_facebook(self, content: str, api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Publish a post to a Facebook Page."""
        if api_credentials and api_credentials.get("page_id") and api_credentials.get("access_token"):
            try:
                import requests
                url = f"https://graph.facebook.com/v19.0/{api_credentials['page_id']}/feed"
                resp = requests.post(
                    url,
                    data={"message": content, "access_token": api_credentials["access_token"]},
                    timeout=15
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("id"):
                    return {"success": True, "result": f"Posted to Facebook (id={data['id']})", "error": None}
                return {"success": False, "result": "", "error": f"Facebook API: {data.get('error', {}).get('message', resp.text)}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"Facebook post failed: {e}"}
        return self._queue_social("facebook", content)

    def post_to_instagram(self, content: str, api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Publish a post to Instagram."""
        if api_credentials and api_credentials.get("account_id") and api_credentials.get("access_token"):
            try:
                import requests
                url = f"https://graph.facebook.com/v19.0/{api_credentials['account_id']}/media"
                resp = requests.post(
                    url,
                    data={"caption": content, "access_token": api_credentials["access_token"]},
                    timeout=15
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("id"):
                    pub_resp = requests.post(
                        f"https://graph.facebook.com/v19.0/{api_credentials['account_id']}/media_publish",
                        data={"creation_id": data["id"], "access_token": api_credentials["access_token"]},
                        timeout=15
                    )
                    if pub_resp.status_code == 200:
                        return {"success": True, "result": "Posted to Instagram", "error": None}
                return {"success": False, "result": "", "error": f"Instagram API: {data}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"Instagram post failed: {e}"}
        return self._queue_social("instagram", content)

    def post_to_tiktok(self, content: str, api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Publish a video or post to TikTok."""
        return self._queue_social("tiktok", content)

    def post_to_linkedin(self, content: str, api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Publish a post to LinkedIn."""
        if api_credentials and api_credentials.get("access_token") and api_credentials.get("person_urn"):
            try:
                import requests
                url = "https://api.linkedin.com/v2/ugcPosts"
                headers = {
                    "Authorization": f"Bearer {api_credentials['access_token']}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "author": api_credentials["person_urn"],
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {
                        "com.linkedin.ugc.ShareContent": {
                            "shareCommentary": {"text": content[:700]},
                            "shareMediaCategory": "NONE"
                        }
                    },
                    "visibility": {"com.linkedin.member.Visibility": "PUBLIC"}
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=15)
                if resp.status_code == 201:
                    return {"success": True, "result": "Posted to LinkedIn", "error": None}
                return {"success": False, "result": "", "error": f"LinkedIn API: {resp.text}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"LinkedIn post failed: {e}"}
        return self._queue_social("linkedin", content)

    def schedule_post(self, content: str, platform: str, scheduled_time: str,
                      api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Schedule a post for future publishing."""
        return self._queue_social(platform, content, scheduled_time)

    def get_social_stats(self, api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Get basic engagement stats."""
        return {"success": True, "result": "Social stats not yet available. Coming soon.", "error": None}

    def _queue_social(self, platform: str, content: str, scheduled: str = "") -> Dict[str, Any]:
        """Queue a social post for later execution."""
        try:
            social_dir = Path("content/social")
            social_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "platform": platform,
                "content": content,
                "status": "pending",
                "scheduled": scheduled or "immediate"
            }
            with open(social_dir / "queue.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            return {"success": True, "result": f"Queued for {platform}", "error": None}
        except Exception as e:
            return {"success": False, "result": "", "error": str(e)}
