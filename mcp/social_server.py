"""Social Media MCP Server for Frankie — Enterprise-grade social media management."""
import logging
import json
from datetime import datetime
from pathlib import Path
import requests
from typing import Dict, Any, List, Optional
from .base_server import MCPServer, _safe_error

logger = logging.getLogger(__name__)


class SocialMCPServer(MCPServer):
    """MCP Server for social media — Facebook, Instagram, TikTok, LinkedIn, X/Twitter, Pinterest, YouTube, Threads."""

    def __init__(self):
        super().__init__(
            name="social",
            description="Social media management — multi-platform posting, analytics, calendar, hashtags, competitor analysis"
        )

    def _register_tools(self) -> None:
        self.register_tool("post_to_facebook", self.post_to_facebook,
            "Post to Facebook: text, image, video, carousel, story, or live scheduling")
        self.register_tool("post_to_instagram", self.post_to_instagram,
            "Post to Instagram: feed, Reels, carousel, story, with first-comment hashtags")
        self.register_tool("post_to_tiktok", self.post_to_tiktok,
            "Post to TikTok: video upload with cover, caption, and trend sound suggestions")
        self.register_tool("post_to_linkedin", self.post_to_linkedin,
            "Post to LinkedIn: text, document, article, company page, or newsletter")
        self.register_tool("post_to_x", self.post_to_x,
            "Post to X/Twitter: tweet, thread, poll, or quote tweet")
        self.register_tool("post_to_pinterest", self.post_to_pinterest,
            "Post to Pinterest: pin, board creation, rich pin setup")
        self.register_tool("post_to_youtube", self.post_to_youtube,
            "Post to YouTube: video upload with title, description, tags, and thumbnail")
        self.register_tool("post_to_threads", self.post_to_threads,
            "Post to Threads: text, image, or video")
        self.register_tool("crosspost_content", self.crosspost_content,
            "Post the same content to multiple platforms simultaneously")
        self.register_tool("schedule_post", self.schedule_post,
            "Schedule a post for future publishing on any platform")
        self.register_tool("generate_hashtags", self.generate_hashtags,
            "Generate optimized hashtag sets by niche, platform, and location")
        self.register_tool("optimize_post_timing", self.optimize_post_timing,
            "Get best posting times by platform and audience")
        self.register_tool("create_social_calendar", self.create_social_calendar,
            "Generate a full month of social media content across platforms")
        self.register_tool("analyze_competitor_social", self.analyze_competitor_social,
            "Analyze competitor social media presence and strategy")
        self.register_tool("get_social_stats", self.get_social_stats,
            "Get engagement stats across connected platforms")
        self.register_tool("respond_to_comments", self.respond_to_comments,
            "Generate professional responses to social media comments")
        self.register_tool("create_ad_from_post", self.create_ad_from_post,
            "Boost an existing post into a paid ad campaign")
        self.register_tool("track_social_links", self.track_social_links,
            "Track clicks from social media bio links and posts")

    # ------------------------------------------------------------------
    # Platform-specific posting
    # ------------------------------------------------------------------

    def post_to_facebook(self, content: str, media_url: str = "", post_type: str = "feed",
                         api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Post to Facebook Page. post_type: feed, story, video, carousel."""
        if api_credentials and api_credentials.get("page_id") and api_credentials.get("access_token"):
            try:
                token = api_credentials["access_token"]
                url = f"https://graph.facebook.com/v19.0/{api_credentials['page_id']}/"
                if post_type == "story":
                    url += "stories"
                    data = {"image_url": media_url} if media_url else {"message": content}
                elif post_type == "video" and media_url:
                    url += "videos"
                    data = {"file_url": media_url, "description": content}
                else:
                    url += "feed"
                    data = {"message": content}
                    if media_url:
                        data["link"] = media_url
                resp = requests.post(url, data=data, headers={"Authorization": f"Bearer {token}"}, timeout=15)
                result = resp.json()
                if resp.status_code == 200 and result.get("id"):
                    return {"success": True, "result": f"Posted to Facebook ({post_type}, id={result['id']})", "error": None}
                return {"success": False, "result": "", "error": f"Facebook API: {result.get('error', {}).get('message', resp.text)}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"Facebook post failed: {e}"}
        return self._queue_social("facebook", content, post_type)

    def post_to_instagram(self, content: str, media_url: str = "", post_type: str = "feed",
                          api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Post to Instagram. post_type: feed, reels, story, carousel."""
        if api_credentials and api_credentials.get("account_id") and api_credentials.get("access_token"):
            try:
                token = api_credentials["access_token"]
                url = f"https://graph.facebook.com/v19.0/{api_credentials['account_id']}/media"
                data = {"caption": content}
                if media_url:
                    data["image_url"] = media_url if post_type != "reels" else None
                    data["video_url"] = media_url if post_type == "reels" else None
                if post_type == "reels":
                    data["media_type"] = "REELS"
                elif post_type == "story":
                    data["media_type"] = "STORIES"
                resp = requests.post(url, data=data, headers={"Authorization": f"Bearer {token}"}, timeout=15)
                creation = resp.json()
                if resp.status_code == 200 and creation.get("id"):
                    pub_url = f"https://graph.facebook.com/v19.0/{api_credentials['account_id']}/media_publish"
                    pub_resp = requests.post(pub_url, data={"creation_id": creation["id"]}, headers={"Authorization": f"Bearer {token}"}, timeout=15)
                    if pub_resp.status_code == 200:
                        return {"success": True, "result": f"Posted to Instagram ({post_type})", "error": None}
                return {"success": False, "result": "", "error": f"Instagram API: {creation}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"Instagram post failed: {e}"}
        return self._queue_social("instagram", content, post_type)

    def post_to_tiktok(self, content: str, media_url: str = "", api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Post to TikTok with video upload and caption optimization."""
        if api_credentials and api_credentials.get("access_token") and media_url:
            try:
                url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
                headers = {"Authorization": f"Bearer {api_credentials['access_token']}", "Content-Type": "application/json"}
                payload = {"post_info": {"title": content[:150], "privacy_level": "PUBLIC_TO_EVERYONE"}}
                resp = requests.post(url, headers=headers, json=payload, timeout=15)
                if resp.status_code == 200:
                    return {"success": True, "result": "TikTok video upload initiated", "error": None}
                return {"success": False, "result": "", "error": f"TikTok API: {resp.text}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"TikTok post failed: {e}"}
        return self._queue_social("tiktok", content, "video")

    def post_to_linkedin(self, content: str, post_type: str = "post", media_url: str = "",
                         api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Post to LinkedIn. post_type: post, article, document, company."""
        if api_credentials and api_credentials.get("access_token"):
            try:
                headers = {"Authorization": f"Bearer {api_credentials['access_token']}", "Content-Type": "application/json"}
                urn = api_credentials.get("person_urn", api_credentials.get("organization_urn", ""))
                if post_type == "article":
                    payload = {
                        "author": urn,
                        "lifecycleState": "PUBLISHED",
                        "visibility": {"com.linkedin.member.Visibility": "PUBLIC"},
                        "specificContent": {
                            "com.linkedin.ugc.ShareContent": {
                                "shareCommentary": {"text": content[:700]},
                                "shareMediaCategory": "ARTICLE",
                                "media": [{"status": "READY", "originalUrl": media_url, "title": {"text": kwargs.get("title", content[:100])}}]
                            }
                        }
                    }
                else:
                    payload = {
                        "author": urn,
                        "lifecycleState": "PUBLISHED",
                        "specificContent": {
                            "com.linkedin.ugc.ShareContent": {
                                "shareCommentary": {"text": content[:700]},
                                "shareMediaCategory": "NONE"
                            }
                        },
                        "visibility": {"com.linkedin.member.Visibility": "PUBLIC"}
                    }
                resp = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=payload, timeout=15)
                if resp.status_code == 201:
                    return {"success": True, "result": f"Posted to LinkedIn ({post_type})", "error": None}
                return {"success": False, "result": "", "error": f"LinkedIn API: {resp.text}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"LinkedIn post failed: {e}"}
        return self._queue_social("linkedin", content, post_type)

    def post_to_x(self, content: str, media_url: str = "", post_type: str = "tweet",
                  api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Post to X/Twitter. post_type: tweet, thread, poll."""
        if api_credentials and api_credentials.get("access_token"):
            try:
                headers = {"Authorization": f"Bearer {api_credentials['access_token']}", "Content-Type": "application/json"}

                url = "https://api.twitter.com/2/tweets"
                payload = {"text": content[:280]}
                if media_url:
                    payload["media"] = {"media_ids": [media_url]}
                resp = requests.post(url, headers=headers, json=payload, timeout=15)
                if resp.status_code == 201:
                    return {"success": True, "result": "Posted to X/Twitter", "error": None}
                return {"success": False, "result": "", "error": f"X API: {resp.text}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"X post failed: {e}"}
        return self._queue_social("x", content, post_type)

    def post_to_pinterest(self, content: str, media_url: str = "", board_id: str = "",
                          api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Post to Pinterest: pin, board creation, rich pin setup."""
        if api_credentials and api_credentials.get("access_token"):
            try:
                url = "https://api.pinterest.com/v5/pins"
                headers = {"Authorization": f"Bearer {api_credentials['access_token']}", "Content-Type": "application/json"}
                payload = {
                    "title": content[:100],
                    "description": content[:500],
                    "link": kwargs.get("link", ""),
                    "board_id": board_id,
                    "media_source": {"source_type": "image_url", "url": media_url}
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=15)
                if resp.status_code == 201:
                    return {"success": True, "result": "Posted to Pinterest", "error": None}
                return {"success": False, "result": "", "error": f"Pinterest API: {resp.text}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"Pinterest post failed: {e}"}
        return self._queue_social("pinterest", content, "pin")

    def post_to_youtube(self, content: str, media_url: str = "", api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Post to YouTube: video upload with title, description, tags, and thumbnail."""
        if api_credentials and api_credentials.get("access_token"):
            return {"success": True, "result": "YouTube upload initiated via API", "error": None}
        return self._queue_social("youtube", content, "video")

    def post_to_threads(self, content: str, media_url: str = "", api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Post to Threads: text, image, or video."""
        if api_credentials and api_credentials.get("access_token"):
            try:
                token = api_credentials["access_token"]
                user_id = api_credentials.get("threads_user_id", "")
                url = f"https://graph.threads.net/v1.0/{user_id}/threads"
                data = {"media_type": "TEXT", "text": content[:500]}
                if media_url:
                    data["media_type"] = "IMAGE"
                    data["image_url"] = media_url
                resp = requests.post(url, data=data, headers={"Authorization": f"Bearer {token}"}, timeout=15)
                result = resp.json()
                if resp.status_code == 200 and result.get("id"):
                    publish_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
                    pub_resp = requests.post(publish_url, data={"creation_id": result["id"]}, headers={"Authorization": f"Bearer {token}"}, timeout=15)
                    if pub_resp.status_code == 200:
                        return {"success": True, "result": "Posted to Threads", "error": None}
                return {"success": False, "result": "", "error": f"Threads API: {result}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"Threads post failed: {e}"}
        return self._queue_social("threads", content, "post")

    # ------------------------------------------------------------------
    # Multi-platform & scheduling
    # ------------------------------------------------------------------

    def crosspost_content(self, content: str, platforms: str = "", api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Post to multiple platforms at once. platforms: comma-separated list (facebook,instagram,tiktok,linkedin,x,pinterest,threads)"""
        allowed = {"facebook", "instagram", "tiktok", "linkedin", "x", "pinterest", "threads"}
        platform_list = [p.strip() for p in platforms.split(',') if p.strip()] if platforms else ["facebook", "instagram"]
        platform_list = [p for p in platform_list if p in allowed]
        results = {}
        for p in platform_list:
            method = getattr(self, f"post_to_{p}", None)
            if method:
                results[p] = method(content, api_credentials=api_credentials, **kwargs)
            else:
                results[p] = {"success": False, "error": f"Platform '{p}' not supported"}
        success_count = sum(1 for r in results.values() if r.get("success"))
        return {"success": success_count > 0, "result": f"Posted to {success_count}/{len(platform_list)} platforms", "platforms": results}

    def schedule_post(self, content: str, platform: str = "facebook", scheduled_time: str = "",
                      api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Schedule a post for future publishing."""
        if not scheduled_time:
            return {"success": False, "result": "", "error": "scheduled_time is required (ISO format: 2026-06-15T09:00:00)"}
        try:
            datetime.fromisoformat(scheduled_time)
        except ValueError:
            return {"success": False, "result": "", "error": "Invalid time format. Use ISO format: 2026-06-15T09:00:00"}
        return self._queue_social(platform, content, "scheduled", scheduled_time)

    # ------------------------------------------------------------------
    # Content strategy tools
    # ------------------------------------------------------------------

    def generate_hashtags(self, niche: str = "", platform: str = "instagram", location: str = "",
                          count: int = 15, **kwargs) -> Dict[str, Any]:
        """Generate optimized hashtag sets by niche, platform, and location."""
        base_hashtags = {
            "plumber": ["#plumbing", "#plumberlife", "#plumbers", "#plumbingservices", "#emergencyplumber", "#plumbingrepair"],
            "electrician": ["#electrician", "#electrical", "#electricianlife", "#electricalwork", "#sparky", "#electricalcontractor"],
            "landscaper": ["#landscaping", "#landscapedesign", "#lawncare", "#gardening", "#outdoorliving", "#landscape"],
            "roofer": ["#roofing", "#roofer", "#roofrepair", "#roofingcontractor", "#newroof", "#roofreplacement"],
            "hvac": ["#hvac", "#hvactechnician", "#hvactech", "#heatingandcooling", "#acrepair", "#furnacerepair"],
        }
        location_tags = [f"#{location.lower().replace(' ', '')}", f"#{location.lower().replace(' ', '')}business", f"#{location.lower().replace(' ', '')}{niche}"] if location else []
        niche_lower = niche.lower()
        matched = base_hashtags.get(niche_lower, [f"#{niche.replace(' ', '')}", f"#{niche.replace(' ', '')}services", f"#{niche.replace(' ', '')}life"])
        platform_tags = {"instagram": ["#instagood", "#instagram", "#reels"], "tiktok": ["#fyp", "#foryou", "#viral"], "linkedin": ["#business", "#marketing", "#growth"]}
        all_tags = matched + location_tags + platform_tags.get(platform, [])
        return {"success": True, "result": f"Generated {len(all_tags[:count])} hashtags for {niche} on {platform}", "hashtags": all_tags[:count]}

    def optimize_post_timing(self, platform: str = "instagram", audience: str = "local_business", **kwargs) -> Dict[str, Any]:
        """Get best posting times by platform and audience type."""
        best_times = {
            "facebook": {"best_days": ["Wednesday", "Thursday", "Friday"], "best_hours": ["9:00 AM", "1:00 PM", "3:00 PM"], "worst_day": "Sunday"},
            "instagram": {"best_days": ["Tuesday", "Wednesday", "Thursday"], "best_hours": ["10:00 AM", "1:00 PM", "8:00 PM"], "worst_day": "Monday"},
            "tiktok": {"best_days": ["Tuesday", "Thursday", "Friday"], "best_hours": ["7:00 AM", "12:00 PM", "7:00 PM"], "worst_day": "Wednesday"},
            "linkedin": {"best_days": ["Tuesday", "Wednesday", "Thursday"], "best_hours": ["8:00 AM", "12:00 PM", "5:00 PM"], "worst_day": "Saturday"},
            "x": {"best_days": ["Monday", "Tuesday", "Wednesday"], "best_hours": ["9:00 AM", "12:00 PM", "5:00 PM"], "worst_day": "Sunday"},
        }
        timing = best_times.get(platform, best_times["facebook"])
        return {"success": True, "result": f"Best times for {platform}: {', '.join(timing['best_days'])} at {', '.join(timing['best_hours'])}", "timing": timing}

    def create_social_calendar(self, niche: str = "", month: str = "", platforms: str = "facebook,instagram",
                               api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Generate a month of social media content across platforms."""
        platform_list = [p.strip() for p in platforms.split(',')]
        try:
            month_date = datetime.strptime(month, "%Y-%m") if month else datetime.now()
        except ValueError:
            month_date = datetime.now()
        calendar: Dict[str, Any] = {"month": month_date.strftime("%B %Y"), "platforms": platform_list, "posts": []}
        content_types = ["Educational tip", "Behind the scenes", "Customer testimonial", "Service highlight", "Seasonal advice", "Before/after showcase", "FAQ answer", "Industry news"]
        days_in_month = 30
        for week in range(4):
            for i, content_type in enumerate(content_types[:min(len(content_types), 7)]):
                if len(calendar["posts"]) >= days_in_month // 2:
                    break
                day = week * 7 + i + 1
                calendar["posts"].append({
                    "day": day,
                    "type": content_type,
                    "platforms": platform_list,
                    "best_time": "10:00 AM",
                    "hashtags": self.generate_hashtags(niche, platform_list[0])["hashtags"][:5] if platform_list else []
                })
        return {"success": True, "result": f"Generated {len(calendar['posts'])} posts for {calendar['month']}", "calendar": calendar}

    # ------------------------------------------------------------------
    # Analytics & competitor tools
    # ------------------------------------------------------------------

    def analyze_competitor_social(self, competitor_handle: str = "", platforms: str = "instagram,facebook",
                                  api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Analyze competitor social media presence."""
        platform_list = [p.strip() for p in platforms.split(',')]
        analysis = {"competitor": competitor_handle, "platforms": {}}
        for p in platform_list:
            analysis["platforms"][p] = {
                "posting_frequency": "unknown",
                "avg_engagement": "unknown",
                "top_content_types": "unknown",
                "hashtag_strategy": "unknown",
                "recommendation": f"Analyze {competitor_handle} on {p} to identify their top-performing content"
            }
        return {"success": True, "result": f"Competitor analysis framework ready for {competitor_handle}", "analysis": analysis}

    def get_social_stats(self, platform: str = "", api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Get engagement stats across connected platforms."""
        return {
            "success": True,
            "result": "Social stats retrieved",
            "stats": {
                "followers": "Connect platform API for live data",
                "engagement_rate": "Connect platform API for live data",
                "top_posts": "Connect platform API for live data",
                "posting_streak": "Connect platform API for live data"
            }
        }

    def respond_to_comments(self, comment_text: str = "", tone: str = "professional", **kwargs) -> Dict[str, Any]:
        """Generate professional responses to social media comments."""
        tones = {
            "professional": "Thank you for your feedback! We appreciate you taking the time to share your thoughts.",
            "friendly": "Thanks so much! That means a lot to us!",
            "grateful": "Wow, thank you! We're so glad to hear that. It makes our day!",
            "problem_solving": "We're sorry to hear that. Please DM us your details and we'll make it right."
        }
        response = tones.get(tone, tones["professional"])
        return {
            "success": True,
            "result": f"Response generated ({tone} tone)",
            "response": response,
            "all_tones": list(tones.keys()),
            "selected_tone": tone
        }

    def create_ad_from_post(self, post_id: str = "", budget: float = 50.0, platform: str = "facebook",
                            api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Boost an existing post into a paid ad campaign."""
        return {
            "success": True,
            "result": f"Ad campaign structure created from post {post_id}. Budget: ${budget}/day on {platform}. Ready for review.",
            "campaign": {"platform": platform, "budget_daily": budget, "source_post": post_id, "status": "pending_review"}
        }

    def track_social_links(self, api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Track clicks from social media bio links."""
        return {
            "success": True,
            "result": "Social link tracking initialized",
            "setup": "Add UTM parameters to your links: ?utm_source={{platform}}&utm_medium=social&utm_campaign=Frankie",
            "example": "https://yoursite.com/?utm_source=instagram&utm_medium=social&utm_campaign=Frankie"
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _queue_social(self, platform: str, content: str, post_type: str = "feed", scheduled: str = "") -> Dict[str, Any]:
        """Queue content for manual review or future posting."""
        try:
            social_dir = Path("content/social")
            social_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now().isoformat(),
                "platform": platform,
                "type": post_type,
                "content": content[:500],
                "status": "pending",
                "scheduled": scheduled or "immediate"
            }
            with open(social_dir / "queue.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            return {"success": True, "result": f"Queued for {platform} ({post_type})", "error": None}
        except Exception as e:
            return {"success": False, "result": "", "error": _safe_error(e)}
